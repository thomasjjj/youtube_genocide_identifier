import asyncio
import logging
from datetime import datetime
from pathlib import Path

# Import from existing modules
from src.youtube_transcript import extract_video_id, get_transcript, save_transcript
from src.youtube_metadata import get_video_metadata, get_video_metadata_pytube
from src.gpt import TranscriptAnalyzer
from config import ensure_dirs_exist, load_env_vars, get_openai_api_key, RESULTS_DIR

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

    # Initialize the transcript analyzer
    analyzer = TranscriptAnalyzer()

    try:
        # Get YouTube URL from user
        youtube_url = input("Enter the YouTube video URL: ")

        # Extract video ID
        video_id = extract_video_id(youtube_url)
        print(f"Extracted video ID: {video_id}")

        # Check if this video has already been analyzed
        has_analysis, prev_analysis = analyzer.check_if_video_analyzed(video_id)

        if has_analysis:
            print(f"\nThis video has already been analyzed on {prev_analysis['analysis_date']}")
            print(f"Previous analysis used model: {prev_analysis['model']}")
            parsed = prev_analysis['parsed_answer']
            print(f"Previous result: {parsed['answer']}")

            reanalyze = input("\nDo you want to reanalyze this video? (y/n): ").strip().lower()
            if reanalyze != 'y':
                # Display the previous analysis
                print("\n===== Previous Genocide Incitement Analysis Result =====")
                print(f"Video: {prev_analysis['video_title']}")
                print(
                    f"Channel: {prev_analysis['channel_name'] if 'channel_name' in prev_analysis else 'Unknown Channel'}")
                print(f"Video ID: {prev_analysis['video_id']}")
                print(f"Analysis Date: {prev_analysis['analysis_date']}")
                print("-" * 60)
                print(f"Question: Does the content incite genocide?")
                print(f"Answer: {parsed['answer']}")
                print("\nReasoning:")
                print(parsed['reasoning'])
                print("\nEvidence:")
                for i, evidence in enumerate(parsed['evidence'], 1):
                    print(f"{i}. {evidence}")
                print("-" * 60)
                print(f"Model: {prev_analysis['model']}")
                print(f"Tokens used: {prev_analysis['tokens_used']}")

                # Exit
                return

        # Continue with transcript extraction
        transcript_record = analyzer.get_transcript_by_video_id(video_id)

        if not transcript_record:
            # We need to fetch and save the transcript
            print(f"\nFetching transcript for video ID: {video_id}...")
            transcript_data = get_transcript(video_id)

            if not transcript_data:
                print("Failed to retrieve transcript. Please check if the video has captions.")
                return

            print("Transcript retrieved successfully!")

            # Try to automatically get video metadata
            video_title, channel_name = get_video_metadata(video_id)

            # If automatic retrieval succeeded, inform the user and give option to override
            if video_title:
                print(f"Automatically retrieved video title: {video_title}")
                override = input("Do you want to override this title? (y/n, press Enter for no): ").strip().lower()
                if override == 'y':
                    video_title = input("Enter the video title: ").strip()
            else:
                # If automatic retrieval failed, ask the user
                video_title = input("Enter the video title (optional, press Enter to skip): ").strip()
                if not video_title:
                    video_title = f"Unknown Title - {video_id}"

            if channel_name:
                print(f"Automatically retrieved channel name: {channel_name}")
                override = input(
                    "Do you want to override this channel name? (y/n, press Enter for no): ").strip().lower()
                if override == 'y':
                    channel_name = input("Enter the channel name: ").strip()
            else:
                channel_name = input("Enter the channel name (optional, press Enter to skip): ").strip()
                if not channel_name:
                    channel_name = "Unknown Channel"

            # Save the transcript to file and database
            formatted_transcripts = []
            for entry in transcript_data:
                formatted_transcripts.append(entry)

            filename, db_success = save_transcript(formatted_transcripts, video_id, video_title, channel_name)

            if not db_success:
                print("Warning: Transcript saved to file but there was an error saving to database.")
                return

            # Get the transcript record from the database
            transcript_record = analyzer.get_transcript_by_video_id(video_id)
        else:
            print(f"\nFound existing transcript for: {transcript_record['video_title']}")
            print(f"Channel: {transcript_record['channel_name']}")

        # Analyze for genocide incitement
        print(f"\nAnalyzing video: {transcript_record['video_title']}")
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

        # Ensure RESULTS_DIR is a Path object
        results_dir = Path(RESULTS_DIR) if isinstance(RESULTS_DIR, str) else RESULTS_DIR

        # Make sure the directory exists
        results_dir.mkdir(parents=True, exist_ok=True)

        # Save the results to a text file in the individual_results directory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        result_filename = results_dir / f"genocide_analysis_{video_id}_{timestamp}.txt"

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

        print(f"\nAnalysis result saved to: {result_filename}")

    except Exception as e:
        logger.error("Error in main application: %s", e, exc_info=True)
        print(f"\nAn error occurred: {str(e)}")
    finally:
        # Clean up connections
        if 'analyzer' in locals():
            analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())