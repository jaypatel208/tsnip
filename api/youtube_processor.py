# youtube_processor.py
import os
import requests
import time
from dotenv import load_dotenv
from datetime import datetime
import threading
import queue

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
YT_DATA_API_V3 = os.getenv("YT_DATA_API_v3")
SUPABASE_YT_TABLE = os.getenv("SUPABASE_YT_TABLE")

# Queue for processing YouTube requests
youtube_queue = queue.Queue()


class YouTubeStreamProcessor:
    def __init__(self):
        self.processing = False
        self.processed_combinations = set()  # To avoid duplicate processing

    def get_live_streams(self, nightbot_chatid, channel_id, timeout=10):
        """
        Fast live stream checker - returns only essential data
        """
        if not YT_DATA_API_V3:
            return {
                "nightbot_chatid": nightbot_chatid,
                "streams": [],
                "error": "No API key",
            }

        streams = []

        try:
            # Get channel name first (single request)
            channel_url = "https://www.googleapis.com/youtube/v3/channels"
            channel_params = {
                "part": "snippet",
                "id": channel_id,
                "key": YT_DATA_API_V3,
            }

            channel_resp = requests.get(
                channel_url, params=channel_params, timeout=timeout
            )
            channel_resp.raise_for_status()

            channel_data = channel_resp.json().get("items", [])
            if not channel_data:
                return {
                    "nightbot_chatid": nightbot_chatid,
                    "streams": [],
                    "error": "Channel not found",
                }

            channel_name = channel_data[0]["snippet"]["title"]

            # Search for streams (live, upcoming, completed)
            search_url = "https://www.googleapis.com/youtube/v3/search"

            # Try different event types
            for event_type in ["live", "upcoming", "completed"]:
                search_params = {
                    "part": "snippet",
                    "channelId": channel_id,
                    "type": "video",
                    "eventType": event_type,
                    "key": YT_DATA_API_V3,
                    "maxResults": 5,
                    "order": "date",
                }

                try:
                    search_resp = requests.get(
                        search_url, params=search_params, timeout=timeout
                    )
                    search_resp.raise_for_status()
                    videos = search_resp.json().get("items", [])

                    for video in videos:
                        video_id = video["id"]["videoId"]
                        streams.append(
                            {
                                "video_id": video_id,
                                "title": video["snippet"]["title"],
                                "status": event_type,
                                "url": f"https://www.youtube.com/watch?v={video_id}",
                                "channel": channel_name,
                            }
                        )

                    # If we found streams, break (prioritize live > upcoming > completed)
                    if streams:
                        break

                except:
                    continue

            return {"nightbot_chatid": nightbot_chatid, "streams": streams}

        except requests.exceptions.Timeout:
            return {
                "nightbot_chatid": nightbot_chatid,
                "streams": [],
                "error": "Timeout",
            }
        except Exception as e:
            return {"nightbot_chatid": nightbot_chatid, "streams": [], "error": str(e)}

    def check_existing_streams(self, chat_id, video_id):
        """Check if stream already exists in database"""
        headers = {
            "apikey": SUPABASE_API_KEY,
            "Authorization": f"Bearer {SUPABASE_API_KEY}",
        }

        try:
            response = requests.get(
                f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?chat_id=eq.{chat_id}&video_id=eq.{video_id}",
                headers=headers,
            )

            if response.status_code == 200:
                existing = response.json()
                return len(existing) > 0
        except:
            pass

        return False

    def insert_yt_streams_to_supabase(self, streams_data):
        """Insert YouTube stream data to yt_db table (only new ones)"""
        if not streams_data.get("streams"):
            print(f"No streams found for chat_id: {streams_data['nightbot_chatid']}")
            return False

        headers = {
            "apikey": SUPABASE_API_KEY,
            "Authorization": f"Bearer {SUPABASE_API_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

        # Filter out existing streams
        new_records = []
        for stream in streams_data["streams"]:
            if not self.check_existing_streams(
                streams_data["nightbot_chatid"], stream["video_id"]
            ):
                record = {
                    "chat_id": streams_data["nightbot_chatid"],
                    "video_id": stream["video_id"],
                    "title": stream["title"],
                    "status": stream["status"],
                    "url": stream["url"],
                    "channel": stream["channel"],
                    "marked": False,
                }
                new_records.append(record)
            else:
                print(f"Stream {stream['video_id']} already exists, skipping...")

        if not new_records:
            print(
                f"No new streams to insert for chat_id: {streams_data['nightbot_chatid']}"
            )
            return True

        # Insert new records
        try:
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}",
                headers=headers,
                json=new_records,
            )

            if response.status_code == 201:
                print(
                    f"Successfully inserted {len(new_records)} new YouTube stream records"
                )
                return True
            else:
                print(f"YouTube streams insert failed: {response.text}")
                return False
        except Exception as e:
            print(f"Error inserting streams: {str(e)}")
            return False

    def process_youtube_request(self, chat_id, channel_id):
        """Process a single YouTube request"""
        combination_key = f"{chat_id}_{channel_id}"

        # Avoid duplicate processing for the same combination
        if combination_key in self.processed_combinations:
            print(f"Skipping duplicate processing for {combination_key}")
            return

        self.processed_combinations.add(combination_key)

        print(
            f"Processing YouTube streams for chat_id: {chat_id}, channel_id: {channel_id}"
        )

        try:
            # Get live streams data
            streams_data = self.get_live_streams(chat_id, channel_id)

            if "error" in streams_data:
                print(f"Error fetching streams: {streams_data['error']}")
                return

            # Insert to yt_db table
            success = self.insert_yt_streams_to_supabase(streams_data)

            if success:
                print(f"YouTube processing completed for {combination_key}")
            else:
                print(f"Failed to store streams for {combination_key}")

        except Exception as e:
            print(f"Error processing YouTube request: {str(e)}")
        finally:
            # Remove from processed set after some time to allow future updates
            threading.Timer(
                300, lambda: self.processed_combinations.discard(combination_key)
            ).start()

    def start_background_processor(self):
        """Start the background processor thread"""
        if self.processing:
            return

        self.processing = True

        def worker():
            print("YouTube background processor started")
            while self.processing:
                try:
                    # Get item from queue with timeout
                    item = youtube_queue.get(timeout=1)
                    chat_id = item.get("chat_id")
                    channel_id = item.get("channel_id")

                    if chat_id and channel_id:
                        self.process_youtube_request(chat_id, channel_id)

                    youtube_queue.task_done()

                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"Background processor error: {str(e)}")

            print("YouTube background processor stopped")

        # Start worker thread
        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()

    def stop_background_processor(self):
        """Stop the background processor"""
        self.processing = False

    def add_to_queue(self, chat_id, channel_id, delay=5):
        """Add a YouTube processing request to the queue with delay"""

        def delayed_add():
            youtube_queue.put(
                {
                    "chat_id": chat_id,
                    "channel_id": channel_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            print(f"Added to YouTube queue: chat_id={chat_id}, channel_id={channel_id}")

        # Add with delay to avoid immediate processing during clip creation
        timer = threading.Timer(delay, delayed_add)
        timer.start()


# Global processor instance
processor = YouTubeStreamProcessor()


def initialize_youtube_processor():
    """Initialize and start the YouTube processor"""
    processor.start_background_processor()
    return processor


def queue_youtube_processing(chat_id, channel_id, delay=5):
    """Queue a YouTube processing request (called from Flask app)"""
    processor.add_to_queue(chat_id, channel_id, delay)


def stop_youtube_processor():
    """Stop the YouTube processor"""
    processor.stop_background_processor()


# Direct execution for testing
if __name__ == "__main__":
    # Test the processor
    processor = initialize_youtube_processor()

    # Example usage
    NIGHTBOT_CHATID = "your_nightbot_chatid_here"
    CHANNEL_ID = "UCrYHJXK4bR9oqEet6St6sWA"

    print("Testing YouTube processor...")
    queue_youtube_processing(NIGHTBOT_CHATID, CHANNEL_ID)

    # Keep running for testing
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping processor...")
        stop_youtube_processor()
