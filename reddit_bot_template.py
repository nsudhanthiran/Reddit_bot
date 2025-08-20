
# Reddit Bot Assessment - Complete Implementation Template
# Author: Assessment Candidate
# Date: August 2025

import praw
import google.generativeai as genai
import sqlite3
import time
import random
import logging
import os
import re
from datetime import datetime
from typing import List, Dict, Optional

class RedditBot:
    def __init__(self, config_file: str = "config.json"):
        """Initialize the Reddit bot with configuration."""
        self.setup_logging()
        self.load_config(config_file)
        self.setup_reddit()
        self.setup_gemini()
        self.setup_database()
        self.processed_posts = set()

    def setup_logging(self):
        """Setup logging system for the bot."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('reddit_bot.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def load_config(self, config_file: str):
        """Load configuration from file."""
        # In a real implementation, load from JSON/YAML file
        self.config = '''
        {
            "reddit": {
                "client_id": "YOUR_REDDIT_CLIENT_ID",
                "client_secret": "YOUR_REDDIT_CLIENT_SECRET",
                "user_agent": "reddit_bot_assessment_v1.0 by /u/your_username",
                "username": "YOUR_BOT_USERNAME",
                "password": "YOUR_BOT_PASSWORD"
            },
            "gemini": {
                "api_key": "YOUR_GEMINI_API_KEY"
            },
            "keywords": [
                "help", "advice", "question", "how to", "need help",
                "confused", "stuck", "problem", "issue", "guidance",
                "suggest", "recommend", "opinion", "thoughts"
            ],
            "subreddits": ["india", "AskReddit"],
            "rate_limits": {
                "reddit_delay": 2,
                "gemini_delay": 12,
                "response_delay": [30, 60]
            }
        }
'''

    def setup_reddit(self):
        """Setup Reddit API connection using PRAW."""
        try:
            self.reddit = praw.Reddit(
                client_id=self.config['reddit']['client_id'],
                client_secret=self.config['reddit']['client_secret'],
                user_agent=self.config['reddit']['user_agent'],
                username=self.config['reddit']['username'],
                password=self.config['reddit']['password']
            )
            # Test the connection
            self.logger.info(f"Connected to Reddit as: {self.reddit.user.me()}")
        except Exception as e:
            self.logger.error(f"Failed to connect to Reddit: {e}")
            raise

    def setup_gemini(self):
        """Setup Gemini API connection."""
        try:
            genai.configure(api_key=self.config['gemini']['api_key'])
            self.gemini_model = genai.GenerativeModel('gemini-2.5-flash')
            self.logger.info("Connected to Gemini API successfully")
        except Exception as e:
            self.logger.error(f"Failed to connect to Gemini: {e}")
            raise

    def setup_database(self):
        """Setup SQLite database for logging interactions."""
        self.conn = sqlite3.connect('reddit_bot.db', check_same_thread=False)
        cursor = self.conn.cursor()

        # Create tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                subreddit TEXT,
                post_id TEXT,
                post_title TEXT,
                post_content TEXT,
                keywords_found TEXT,
                bot_response TEXT,
                response_length INTEGER,
                success BOOLEAN
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                total_posts_scanned INTEGER,
                posts_responded_to INTEGER,
                response_rate REAL,
                average_response_time REAL
            )
        ''')

        self.conn.commit()
        self.logger.info("Database setup complete")

    def detect_keywords(self, text: str) -> List[str]:
        """Detect keywords in the given text."""
        found_keywords = []
        text_lower = text.lower()

        for keyword in self.config['keywords']:
            if keyword.lower() in text_lower:
                found_keywords.append(keyword)

        return found_keywords

    def should_respond_to_post(self, post) -> tuple[bool, List[str]]:
        """Determine if the bot should respond to this post."""
        # Skip if already processed
        if post.id in self.processed_posts:
            return False, []

        # Skip if post is too old (more than 1 hour)
        post_age = time.time() - post.created_utc
        if post_age > 3600:  # 1 hour
            return False, []

        # Check for keywords in title and content
        title_keywords = self.detect_keywords(post.title)
        content_keywords = self.detect_keywords(post.selftext) if hasattr(post, 'selftext') else []

        all_keywords = list(set(title_keywords + content_keywords))

        # Respond if keywords found and post has engagement potential
        if all_keywords and post.score >= 0:
            return True, all_keywords

        return False, []

    def generate_response(self, post, keywords: List[str]) -> str:
        """Generate a contextual response using Gemini API."""
        try:
            # Create a context-aware prompt
            prompt = f"""You are a curious and helpful Redditor. Instead of just giving a direct answer, your goal is to help the original poster think through their problem by asking insightful questions, while still providing a bit of guidance.

**Instructions**
*   You are thoughtful and encouraging.
*   You lead with questions before offering a strong opinion.
*   Your tone is conversational and friendly.
*   Be direct, practical, and genuinely helpful. Sound like a real person, not an AI.
**Post Details:**
- Title: {post.title}
- Content: {post.selftext[:500] if hasattr(post, 'selftext') else 'No content'}
- Subreddit: r/{post.subreddit.display_name}
- Keywords found: {', '.join(keywords)}
Based on this, draft a comment that helps the user reflect on their own goals. End with an open-ended question.
"""

            # Generate response with rate limiting
            response = self.gemini_model.generate_content(prompt)

            # Add human-like delay
            time.sleep(self.config['rate_limits']['gemini_delay'])

            return response.text

        except Exception as e:
            self.logger.error(f"Error generating response: {e}")
            return None

    def post_response(self, post, response_text: str) -> bool:
        """Post the response to Reddit with anti-spam measures."""
        try:
            # Add random delay to mimic human behavior
            delay = random.randint(*self.config['rate_limits']['response_delay'])
            self.logger.info(f"Waiting {delay} seconds before posting response...")
            time.sleep(delay)

            # Post the comment
            comment = post.reply(response_text)
            self.logger.info(f"Successfully posted response to {post.id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to post response: {e}")
            return False

    def log_interaction(self, post, keywords: List[str], response: str, success: bool):
        """Log the interaction to database."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO interactions 
            (timestamp, subreddit, post_id, post_title, post_content, 
             keywords_found, bot_response, response_length, success)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            post.subreddit.display_name,
            post.id,
            post.title,
            post.selftext[:500] if hasattr(post, 'selftext') else '',
            ', '.join(keywords),
            response,
            len(response) if response else 0,
            success
        ))
        self.conn.commit()

    def scan_subreddit(self, subreddit_name: str, limit: int = 10):
        """Scan a subreddit for new posts to respond to."""
        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            posts_scanned = 0
            posts_responded = 0

            self.logger.info(f"Scanning r/{subreddit_name} for new posts...")

            # Get new posts from the subreddit
            for post in subreddit.new(limit=limit):
                posts_scanned += 1

                should_respond, keywords = self.should_respond_to_post(post)

                if should_respond:
                    self.logger.info(f"Found relevant post: {post.title[:50]}...")

                    # Generate response
                    response = self.generate_response(post, keywords)

                    if response:
                        # Post response
                        success = self.post_response(post, response)

                        # Log interaction
                        self.log_interaction(post, keywords, response, success)

                        if success:
                            posts_responded += 1
                            self.processed_posts.add(post.id)

                # Rate limiting for Reddit API
                time.sleep(self.config['rate_limits']['reddit_delay'])

            self.logger.info(f"Scanned {posts_scanned} posts, responded to {posts_responded}")

        except Exception as e:
            self.logger.error(f"Error scanning subreddit {subreddit_name}: {e}")

    def run_hourly_scan(self):
        """Run the bot for one hour cycle."""
        start_time = time.time()

        self.logger.info("Starting hourly scan cycle...")

        for subreddit_name in self.config['subreddits']:
            self.scan_subreddit(subreddit_name, limit=25)

        elapsed_time = time.time() - start_time
        self.logger.info(f"Hourly scan completed in {elapsed_time:.2f} seconds")

    def run_continuous(self):
        """Run the bot continuously with hourly scans."""
        self.logger.info("Starting continuous bot operation...")

        try:
            while True:
                self.run_hourly_scan()

                # Wait for next hour
                self.logger.info("Waiting for next scan cycle...")
                #time.sleep(3600)  # 1 hour
                time.sleep(600) #10 mins
        except KeyboardInterrupt:
            self.logger.info("Bot stopped by user")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources before shutdown."""
        if hasattr(self, 'conn'):
            self.conn.close()
        self.logger.info("Bot shutdown complete")

# Configuration file template
config_template = '''
{
    "reddit": {
        "client_id": "YOUR_REDDIT_CLIENT_ID",
        "client_secret": "YOUR_REDDIT_CLIENT_SECRET",
        "user_agent": "reddit_bot_assessment_v1.0 by /u/your_username",
        "username": "YOUR_BOT_USERNAME",
        "password": "YOUR_BOT_PASSWORD"
    },
    "gemini": {
        "api_key": "YOUR_GEMINI_API_KEY"
    },
    "keywords": [
        "help", "advice", "question", "how to", "need help",
        "confused", "stuck", "problem", "issue", "guidance",
        "suggest", "recommend", "opinion", "thoughts"
    ],
    "subreddits": ["india", "AskReddit"],
    "rate_limits": {
        "reddit_delay": 2,
        "gemini_delay": 12,
        "response_delay": [30, 60]
    }
}
'''

# Main execution
if __name__ == "__main__":
    # Create bot instance and run
    bot = RedditBot()

    # For testing, run single scan
    #bot.run_hourly_scan()

    # For continuous operation
    bot.run_continuous()
