import subprocess
import json
import logging
from typing import Tuple, Optional

# Configure module-level logger
logger = logging.getLogger(__name__)


def get_video_metadata(video_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Retrieve video title and channel name using yt-dlp without requiring a YouTube API key.

    Args:
        video_id (str): The YouTube video ID

    Returns:
        Tuple[Optional[str], Optional[str]]: A tuple containing (video_title, channel_name)
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        # Check if yt-dlp is installed
        try:
            subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.warning("yt-dlp not found. Trying pytube instead.")
            return get_video_metadata_pytube(video_id)

        # Use yt-dlp to extract video metadata in JSON format
        # Only request metadata (no download), with the fields we need
        command = [
            "yt-dlp",
            "--dump-json",
            "--no-download",
            "--skip-download",
            "--print-json",
            video_url
        ]

        # Run the command and capture the output
        result = subprocess.run(command, capture_output=True, text=True, check=True)

        # Parse the JSON output
        video_info = json.loads(result.stdout)

        # Extract the relevant information
        video_title = video_info.get('title')
        channel_name = video_info.get('channel', video_info.get('uploader'))

        return video_title, channel_name

    except subprocess.SubprocessError as e:
        logger.warning(f"Error running yt-dlp: {e}")
        return get_video_metadata_pytube(video_id)
    except json.JSONDecodeError as e:
        logger.warning(f"Error parsing yt-dlp output: {e}")
        return get_video_metadata_pytube(video_id)
    except Exception as e:
        logger.warning(f"Error retrieving video metadata with yt-dlp: {e}")
        return get_video_metadata_pytube(video_id)


def get_video_metadata_pytube(video_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Alternative method using pytube to retrieve video title and channel name.

    Args:
        video_id (str): The YouTube video ID

    Returns:
        Tuple[Optional[str], Optional[str]]: A tuple containing (video_title, channel_name)
    """
    try:
        # Importing pytube here to make it optional
        from pytube import YouTube

        # Create YouTube object
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        yt = YouTube(video_url)

        # Extract video title and channel name
        video_title = yt.title
        channel_name = yt.author

        return video_title, channel_name

    except ImportError:
        logger.warning("pytube not installed. Neither yt-dlp nor pytube available for metadata retrieval.")
        return None, None
    except Exception as e:
        logger.warning(f"Error retrieving video metadata with pytube: {e}")
        return None, None