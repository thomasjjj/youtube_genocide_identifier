import asyncio
import logging
from datetime import datetime

# Import from existing modules
from youtube_transcript import extract_video_id, get_transcript, save_transcript
from gpt import TranscriptAnalyzer
from config import ensure_dirs_exist, load_env_vars, get_openai_api_key

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def main():
    """
    Main application logic for YouTube transcript analysis for incitement to genocide.
    """
    print("\n===== YouTube Genocide Incitement Analysis Tool =====\n")
    print("This tool analyzes YouTube video transcripts to determine if they contain")
    print("content that qualifies as incitement to genocide according to")
    print("international law standards and the Rome Statute.\n")

    # Initialize environment
    ensure_dirs_exist()
    load_env_vars()
    get_openai_api_key()  # Ensure we have the API key

    # Get YouTube URL from user
    youtube_url = input("Enter the YouTube video URL: ")

    try:
        # Extract video ID
        video_id = extract_video_id(youtube_url)
        print(f"Extracted video ID: {video_id}")

        # Get video title (optional)
        video_title = input("Enter the video title (optional, press Enter to skip): ").strip()
        if not video_title:
            video_title = f"Unknown Title - {video_id}"

        # Get channel name (optional)
        channel_name = input("Enter the channel name (optional, press Enter to skip): ").strip()
        if not channel_name:
            channel_name = "Unknown Channel"

        # Get the transcript
        print(f"\nFetching transcript for video ID: {video_id}...")
        transcript_data = get_transcript(video_id)

        if not transcript_data:
            print("Failed to retrieve transcript. Please check if the video has captions.")
            return

        print("Transcript retrieved successfully!")

        # Save the transcript to file and database
        formatted_transcripts = []
        for entry in transcript_data:
            formatted_transcripts.append(entry)

        filename, db_success = save_transcript(formatted_transcripts, video_id, video_title)

        if not db_success:
            print("Warning: Transcript saved to file but there was an error saving to database.")
            return

        # Initialize the transcript analyzer
        analyzer = TranscriptAnalyzer()

        # Get the most recent transcript from the database
        transcript_record = analyzer.get_transcript_by_video_id(video_id)

        if not transcript_record:
            print("Error: Transcript not found in database. Please try again.")
            return

        # Update the channel name in the database (since our save_transcript doesn't set it properly)
        if channel_name != "Unknown Channel":
            conn = analyzer.conn
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE transcripts SET channel_name = ? WHERE id = ?",
                (channel_name, transcript_record['id'])
            )
            conn.commit()
            transcript_record['channel_name'] = channel_name

        # Analyze for genocide incitement
        print(f"\nAnalyzing video: {video_title}")
        print("Analysis: Checking for incitement to genocide based on Rome Statute definition")
        print("Processing with OpenAI... (this may take a moment)")

        result = await analyzer.analyze_genocide_incitement(transcript_record)

        if "error" in result:
            print(f"\nError during analysis: {result['error']}")
            return

        # Print the result in a user-friendly format
        print("\n===== Genocide Incitement Analysis Result =====")
        print(f"Video: {transcript_record['video_title']}")
        print(f"Channel: {transcript_record['channel_name']}")
        print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * 60)
        print(f"Question: Does the content incite genocide?")
        print(f"Answer: {result['answer']}")
        print("\nReasoning:")
        print(result['reasoning'])
        print("\nEvidence:")
        for i, evidence in enumerate(result['evidence'], 1):
            print(f"{i}. {evidence}")
        print("-" * 60)
        print(f"Model: {result['model']}")
        print(f"Tokens used: {result['tokens_used']}")

        # Save the results to a text file for reference
        result_filename = f"genocide_analysis_{video_id}.txt"
        with open(result_filename, 'w', encoding='utf-8') as f:
            f.write(f"GENOCIDE INCITEMENT ANALYSIS RESULT\n")
            f.write(f"================================\n\n")
            f.write(f"Video: {transcript_record['video_title']}\n")
            f.write(f"Channel: {transcript_record['channel_name']}\n")
            f.write(f"Video ID: {video_id}\n")
            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"QUESTION: Does the content incite genocide?\n")
            f.write(f"ANSWER: {result['answer']}\n\n")
            f.write(f"REASONING:\n{result['reasoning']}\n\n")
            f.write(f"EVIDENCE:\n")
            for i, evidence in enumerate(result['evidence'], 1):
                f.write(f"{i}. {evidence}\n")
            f.write(f"\nAnalysis performed using: {result['model']}\n")
            f.write(f"Tokens used: {result['tokens_used']}\n")

        print(f"\nAnalysis result also saved to: {result_filename}")

    except Exception as e:
        logger.error("Error in main application: %s", e, exc_info=True)
        print(f"\nAn error occurred: {str(e)}")
    finally:
        # Clean up connections
        if 'analyzer' in locals():
            analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())