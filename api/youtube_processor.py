import os
import requests
import time
from dotenv import load_dotenv
from datetime import datetime
import threading
import queue
import logging

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
YT_DATA_API_V3 = os.getenv("YT_DATA_API_V3")
SUPABASE_YT_TABLE = os.getenv("SUPABASE_YT_TABLE")

youtube_queue = queue.Queue()

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class YouTubeStreamProcessor:
    def __init__(self):
        self.processing = False

    def get_live_streams(self, nightbot_chatid, channel_id, timeout=10):
        if not YT_DATA_API_V3:
            return {
                "nightbot_chatid": nightbot_chatid,
                "streams": [],
                "error": "No API key",
            }

        streams = []

        try:
            # Get channel name
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
            items = channel_resp.json().get("items", [])
            if not items:
                return {
                    "nightbot_chatid": nightbot_chatid,
                    "streams": [],
                    "error": "Channel not found",
                }

            channel_name = items[0]["snippet"]["title"]
            logger.info(f"Found channel: {channel_name}")

            # Try event types - prioritize live, then completed
            for event_type in ["live", "completed"]:
                logger.info(f"Searching for {event_type} streams...")
                search_url = "https://www.googleapis.com/youtube/v3/search"
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
                    resp = requests.get(
                        search_url, params=search_params, timeout=timeout
                    )
                    resp.raise_for_status()
                    videos = resp.json().get("items", [])

                    # Collect video IDs for batch processing
                    video_ids = [video["id"]["videoId"] for video in videos]

                    # Get live streaming details for all videos in batch
                    streaming_details = {}
                    if video_ids:
                        video_details_url = (
                            "https://www.googleapis.com/youtube/v3/videos"
                        )
                        video_details_params = {
                            "part": "liveStreamingDetails",
                            "id": ",".join(video_ids),
                            "key": YT_DATA_API_V3,
                        }

                        try:
                            details_resp = requests.get(
                                video_details_url,
                                params=video_details_params,
                                timeout=timeout,
                            )
                            details_resp.raise_for_status()
                            details_items = details_resp.json().get("items", [])

                            for item in details_items:
                                video_id = item["id"]
                                live_details = item.get("liveStreamingDetails", {})
                                streaming_details[video_id] = {
                                    "start_time": live_details.get("actualStartTime"),
                                    "end_time": live_details.get("actualEndTime"),
                                }
                        except requests.exceptions.RequestException as e:
                            logger.error(
                                f"Error getting live streaming details: {str(e)}"
                            )
                            # Continue without streaming details if this fails

                    for video in videos:
                        video_id = video["id"]["videoId"]
                        stream_info = {
                            "video_id": video_id,
                            "title": video["snippet"]["title"],
                            "status": event_type,
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "channel": channel_name,
                            "channel_id": channel_id,
                        }

                        # Add streaming details if available
                        if video_id in streaming_details:
                            stream_info["start_time"] = streaming_details[video_id][
                                "start_time"
                            ]
                            stream_info["end_time"] = streaming_details[video_id][
                                "end_time"
                            ]
                        else:
                            stream_info["start_time"] = None
                            stream_info["end_time"] = None

                        streams.append(stream_info)

                    if streams:
                        logger.info(f"Found {len(streams)} {event_type} streams")
                        break  # Stop after finding streams of the first available type

                except requests.exceptions.RequestException as e:
                    logger.error(f"Error searching for {event_type} streams: {str(e)}")
                    continue
                except Exception as e:
                    logger.error(
                        f"Unexpected error searching for {event_type} streams: {str(e)}"
                    )
                    continue

            return {"nightbot_chatid": nightbot_chatid, "streams": streams}

        except requests.exceptions.Timeout:
            logger.error(f"Timeout getting streams for channel {channel_id}")
            return {
                "nightbot_chatid": nightbot_chatid,
                "streams": [],
                "error": "Timeout",
            }
        except Exception as e:
            logger.error(f"Error getting streams for channel {channel_id}: {str(e)}")
            return {"nightbot_chatid": nightbot_chatid, "streams": [], "error": str(e)}

    def check_existing_streams(self, chat_id, video_id):
        headers = {
            "apikey": SUPABASE_API_KEY,
            "Authorization": f"Bearer {SUPABASE_API_KEY}",
        }
        try:
            url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?chat_id=eq.{chat_id}&video_id=eq.{video_id}"
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                exists = len(resp.json()) > 0
                logger.debug(f"Stream {video_id} exists: {exists}")
                return exists
            else:
                logger.warning(
                    f"Failed to check existing stream {video_id}: {resp.status_code}"
                )
        except Exception as e:
            logger.error(f"Error checking existing stream {video_id}: {str(e)}")
        return False

    def insert_yt_streams_to_supabase(self, streams_data):
        if not streams_data.get("streams"):
            logger.info(
                f"No streams found for chat_id: {streams_data['nightbot_chatid']}"
            )
            return False

        headers = {
            "apikey": SUPABASE_API_KEY,
            "Authorization": f"Bearer {SUPABASE_API_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

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
                    "channel_id": stream["channel_id"],
                    "marked": False,
                }

                # Add stream timing information if available
                if stream.get("start_time"):
                    record["stream_start_time"] = stream["start_time"]

                new_records.append(record)
            else:
                logger.info(f"Stream {stream['video_id']} already exists, skipping...")

        if not new_records:
            logger.info(
                f"No new streams to insert for chat_id: {streams_data['nightbot_chatid']}"
            )
            return True

        try:
            resp = requests.post(
                f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}",
                headers=headers,
                json=new_records,
            )
            if resp.status_code == 201:
                logger.info(f"✓ Inserted {len(new_records)} new YouTube stream records")
                return True
            else:
                logger.error(f"✗ YouTube insert failed: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"✗ Error inserting streams: {str(e)}")
            return False

    def process_youtube_request(self, chat_id, channel_id):
        logger.info(
            f"Processing YouTube request: chat_id={chat_id}, channel_id={channel_id}"
        )

        try:
            streams_data = self.get_live_streams(chat_id, channel_id)
            if "error" in streams_data:
                logger.error(f"Stream error: {streams_data['error']}")
                return False

            success = self.insert_yt_streams_to_supabase(streams_data)
            if success:
                logger.info(
                    f"✓ YouTube processing complete for chat_id={chat_id}, channel_id={channel_id}"
                )
                return True
            else:
                logger.error(
                    f"✗ YouTube processing failed for chat_id={chat_id}, channel_id={channel_id}"
                )
                return False
        except Exception as e:
            logger.error(f"✗ Exception during YouTube processing: {str(e)}")
            return False

    def start_background_processor(self):
        if self.processing:
            logger.warning("Background processor already running")
            return
        self.processing = True

        def worker():
            logger.info("YouTube background processor started")
            while self.processing:
                try:
                    item = youtube_queue.get(timeout=1)
                    chat_id = item.get("chat_id")
                    channel_id = item.get("channel_id")
                    if chat_id and channel_id:
                        self.process_youtube_request(chat_id, channel_id)
                    youtube_queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Background processing error: {str(e)}")
            logger.info("YouTube background processor stopped")

        threading.Thread(target=worker, daemon=True).start()

    def stop_background_processor(self):
        logger.info("Stopping background processor...")
        self.processing = False

    def add_to_queue(self, chat_id, channel_id, delay=5):
        def delayed_add():
            youtube_queue.put(
                {
                    "chat_id": chat_id,
                    "channel_id": channel_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            logger.info(
                f"Added to YouTube queue: chat_id={chat_id}, channel_id={channel_id}"
            )

        threading.Timer(delay, delayed_add).start()
        logger.info(f"Scheduled YouTube processing in {delay} seconds")


# Global instance
processor = YouTubeStreamProcessor()


def initialize_youtube_processor():
    processor.start_background_processor()
    return processor


def queue_youtube_processing(chat_id, channel_id, delay=5):
    processor.add_to_queue(chat_id, channel_id, delay)


def stop_youtube_processor():
    processor.stop_background_processor()


def process_youtube_request(chat_id, channel_id):
    return processor.process_youtube_request(chat_id, channel_id)


if __name__ == "__main__":
    processor = initialize_youtube_processor()
    NIGHTBOT_CHATID = "your_nightbot_chatid_here"
    CHANNEL_ID = "UCrYHJXK4bR9oqEet6St6sWA"
    logger.info("Testing YouTube processor with direct call...")
    result = processor.process_youtube_request(NIGHTBOT_CHATID, CHANNEL_ID)
    logger.info(f"Result: {result}")
    time.sleep(10)
    logger.info("Done.")
