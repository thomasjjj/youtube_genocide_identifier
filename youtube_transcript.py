import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs

# Import configuration settings
from config import DATA_DIR, DB_PATH, TRANSCRIPTS_DIR, ensure_dirs_exist


def extract_video_id(youtube_url):
    """
    Extract the video ID from a YouTube URL.

    Args:
        youtube_url (str): The URL of the YouTube video.

    Returns:
        str: The video ID extracted from the URL.
    """
    # Parse the URL
    parsed_url = urlparse(youtube_url)

    # For URLs like: https://www.youtube.com/watch?v=VIDEO_ID
    if parsed_url.hostname in ('www.youtube.com', 'youtube.com'):
        if parsed_url.path == '/watch':
            return parse_qs(parsed_url.query)['v'][0]
        # For URLs like: https://www.youtube.com/embed/VIDEO_ID
        elif parsed_url.path.startswith('/embed/'):
            return parsed_url.path.split('/')[2]
        # For URLs like: https://www.youtube.com/v/VIDEO_ID
        elif parsed_url.path.startswith('/v/'):
            return parsed_url.path.split('/')[2]
    # For URLs like: https://youtu.be/VIDEO_ID
    elif parsed_url.hostname == 'youtu.be':
        return parsed_url.path[1:]

    # If no valid video ID is found
    raise ValueError("Invalid YouTube URL. Could not extract video ID.")


def get_transcript(video_id, languages=['en']):
    """
    Get the transcript for a YouTube video.

    Args:
        video_id (str): The ID of the YouTube video.
        languages (list): List of language codes to try.

    Returns:
        list: A list of transcript entries, each with text and timestamp.
    """
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        return transcript
    except Exception as e:
        print(f"Error fetching transcript: {e}")
        return None


def format_transcript(transcript):
    """
    Format the transcript into a readable string.

    Args:
        transcript (list): List of transcript entries.

    Returns:
        str: Formatted transcript.
    """
    if not transcript:
        return "No transcript available."

    formatted_text = ""
    for entry in transcript:
        start_time = format_time(entry['start'])
        text = entry['text']
        formatted_text += f"[{start_time}] {text}\n"

    return formatted_text


def format_time(seconds):
    """
    Format time in seconds to MM:SS format.

    Args:
        seconds (float): Time in seconds.

    Returns:
        str: Formatted time.
    """
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes:02d}:{seconds:02d}"


def save_transcript(transcript, video_id, video_title=None):
    """
    Save the transcript to a file and database.

    Args:
        transcript (list): Raw transcript data.
        video_id (str): YouTube video ID.
        video_title (str, optional): Title of the video.

    Returns:
        tuple: (filename, success)
    """
    # Ensure directories exist
    ensure_dirs_exist()

    # Format the transcript for file storage
    formatted_transcript = format_transcript(transcript)

    # Generate a filename for the transcript file
    safe_id = video_id.replace("/", "_").replace("\\", "_")
    title_suffix = f"_{video_title}" if video_title else ""
    safe_title = re.sub(r'[^\w\s-]', '', title_suffix.replace(" ", "_"))
    filename = TRANSCRIPTS_DIR / f"transcript_{safe_id}{safe_title}.txt"

    # Save the transcript to a file
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(formatted_transcript)

    print(f"Transcript saved to {filename}")

    # Save the transcript to the database
    try:
        # Create a connection to the database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Create the transcripts table if it doesn't exist
        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS transcripts
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           video_id
                           TEXT
                           NOT
                           NULL,
                           video_title
                           TEXT,
                           channel_name
                           TEXT,
                           transcript_text
                           TEXT
                           NOT
                           NULL,
                           extraction_date
                           TIMESTAMP
                           NOT
                           NULL
                       )
                       ''')

        # Insert the transcript into the database
        cursor.execute('''
                       INSERT INTO transcripts (video_id, video_title, channel_name, transcript_text, extraction_date)
                       VALUES (?, ?, ?, ?, ?)
                       ''', (
                           video_id,
                           video_title or f"Unknown Title - {video_id}",
                           "Unknown Channel",  # This could be fetched from the YouTube API with a separate function
                           "\n".join([entry['text'] for entry in transcript]),
                           datetime.now().isoformat()
                       ))

        conn.commit()
        conn.close()

        print(f"Transcript saved to database for video ID: {video_id}")
        return filename, True

    except Exception as e:
        print(f"Error saving transcript to database: {e}")
        return filename, False


def main():
    # Ensure directories exist
    ensure_dirs_exist()

    # Get the YouTube URL from the user
    youtube_url = input("Enter the YouTube video URL: ")

    try:
        # Extract the video ID
        video_id = extract_video_id(youtube_url)

        # Optional: Ask for video title
        video_title = input("Enter the video title (optional, press Enter to skip): ").strip()
        if not video_title:
            video_title = f"Unknown Title - {video_id}"

        # Get the transcript
        transcript_data = get_transcript(video_id)

        if transcript_data:
            # Save the transcript
            filename, db_success = save_transcript(transcript_data, video_id, video_title)

            # Preview the transcript
            with open(filename, 'r', encoding='utf-8') as f:
                preview = f.read(500)

            print("\nTranscript Preview:")
            print(preview + "...\n")

            if db_success:
                print("Transcript successfully saved to file and database.")
            else:
                print("Transcript saved to file but there was an error saving to database.")
        else:
            print("Could not retrieve transcript.")

    except ValueError as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()