import os
import requests
from dotenv import load_dotenv

load_dotenv()
YT_API_KEY = os.getenv("YT_DATA_API_v3")

def get_live_streams(nightbot_chatid, channel_id, timeout=10):
    """
    Fast live stream checker - returns only essential data
    
    Args:
        nightbot_chatid: Your Nightbot chat ID
        channel_id: YouTube channel ID
        timeout: Request timeout (default: 10s)
    
    Returns:
        dict: {
            'nightbot_chatid': str,
            'streams': [
                {
                    'video_id': str,
                    'title': str,
                    'status': str,
                    'url': str,
                    'channel': str
                }
            ]
        }
    """
    
    if not YT_API_KEY:
        return {'nightbot_chatid': nightbot_chatid, 'streams': [], 'error': 'No API key'}
    
    streams = []
    
    try:
        # Get channel name first (single request)
        channel_url = "https://www.googleapis.com/youtube/v3/channels"
        channel_params = {'part': 'snippet', 'id': channel_id, 'key': YT_API_KEY}
        
        channel_resp = requests.get(channel_url, params=channel_params, timeout=timeout)
        channel_resp.raise_for_status()
        
        channel_data = channel_resp.json().get('items', [])
        if not channel_data:
            return {'nightbot_chatid': nightbot_chatid, 'streams': [], 'error': 'Channel not found'}
        
        channel_name = channel_data[0]['snippet']['title']
        
        # Search for streams (live, upcoming, completed)
        search_url = "https://www.googleapis.com/youtube/v3/search"
        
        # Try different event types
        for event_type in ['live', 'upcoming', 'completed']:
            search_params = {
                'part': 'snippet',
                'channelId': channel_id,
                'type': 'video',
                'eventType': event_type,
                'key': YT_API_KEY,
                'maxResults': 5,
                'order': 'date'
            }
            
            try:
                search_resp = requests.get(search_url, params=search_params, timeout=timeout)
                search_resp.raise_for_status()
                videos = search_resp.json().get('items', [])
                
                for video in videos:
                    video_id = video['id']['videoId']
                    streams.append({
                        'video_id': video_id,
                        'title': video['snippet']['title'],
                        'status': event_type,
                        'url': f"https://www.youtube.com/watch?v={video_id}",
                        'channel': channel_name
                    })
                
                # If we found streams, break (prioritize live > upcoming > completed)
                if streams:
                    break
                    
            except:
                continue
        
        return {
            'nightbot_chatid': nightbot_chatid,
            'streams': streams
        }
        
    except requests.exceptions.Timeout:
        return {'nightbot_chatid': nightbot_chatid, 'streams': [], 'error': 'Timeout'}
    except Exception as e:
        return {'nightbot_chatid': nightbot_chatid, 'streams': [], 'error': str(e)}

# Example usage
if __name__ == "__main__":
    # Your inputs
    NIGHTBOT_CHATID = "your_nightbot_chatid_here"
    CHANNEL_ID = "UCrYHJXK4bR9oqEet6St6sWA"
    
    result = get_live_streams(NIGHTBOT_CHATID, CHANNEL_ID)
    
    print(f"Nightbot Chat ID: {result['nightbot_chatid']}")
    
    if 'error' in result:
        print(f"Error: {result['error']}")
    elif result['streams']:
        print(f"Found {len(result['streams'])} streams:")
        for stream in result['streams']:
            print(f"- Video ID: {stream['video_id']}")
            print(f"  Title: {stream['title']}")
            print(f"  Status: {stream['status']}")
            print(f"  URL: {stream['url']}")
            print(f"  Channel: {stream['channel']}")
            print()
    else:
        print("No live streams found")