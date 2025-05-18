#!/usr/bin/env python3
"""
MuxTools Automation Script for Anime Muxing.

This script automates the process of muxing anime episodes using MuxTools.
It supports batch processing of episodes, custom flags/naming, and dry-run mode.
The script handles video, audio, subtitles, fonts, and chapters in a standardized way.

Usage:
    python script.py <episode> [outdir] [options]

    <episode>: Episode specification:
               - Single number: "1"
               - Comma-separated list: "1,3,5"
               - Range: "1-5"
               - Mixed format: "1-3,5,7-9"
               - All episodes: "all"
    [outdir]: Output directory (default: "muxed")

Options:
    -v, --version: Version number for the release
    -f, --flag: Group tag to include in the filename
    -d, --dry-run: Test the muxing process without actually creating files
"""

import argparse
import re
import sys
from enum import Flag, auto
from pathlib import Path
from typing import List, Optional

try:
    from muxtools import (
        AudioFile,
        Chapters,
        GlobSearch,
        LoggingException,
        Premux,
        Setup,
        SubFile,
        TmdbConfig,
        log,
        mux,
    )
except ImportError as e:
    raise ImportError(
        "The 'muxtools' module is not installed. Please install it using 'pip install git+https://github.com/Jaded-Encoding-Thaumaturgy/muxtools/'."
    ) from e


class RunMode(Flag):
    """Flag enum to control script behavior."""

    NORMAL = 0
    DRYRUN = auto()


# Show configuration (edit these values)
showName = "JudulAnime"  # Name of the anime show
dirPremux = r""
dirAudio = r""
dirSub = r""
intTmdb = 0  # TMDB ID for the show (0 if not used)


def mux_episode(
    episode_number: int,
    out_dir: str = "muxed",
    version: int = 1,
    flag: str = "testing",
    mode: RunMode = RunMode.NORMAL,
) -> Optional[Path]:
    """
    Mux a single anime episode into an MKV file.

    This function handles the entire muxing process for a single episode, including
    finding the video source, audio, subtitles, fonts, and chapters, and then combining
    them into a properly formatted MKV file with appropriate metadata.

    Args:
        episode_number: The episode number to mux
        out_dir: Directory where the output MKV file will be saved
        version: Version number of the release (defaults to 1, not shown if 1)
        flag: Group/tag name to include in the filename
        mode: Controls whether to actually mux or just do a dry run

    Returns:
        Path object to the created MKV file or None in dry-run mode or if muxing failed

    Raises:
        LoggingException: If a critical error occurs during muxing
    """
    # Format version string (empty for v1)
    verstr = "" if version == 1 else f"v{version}"

    # Initialize setup with appropriate episode and naming conventions
    setup = Setup(
        f"{episode_number:02d}",
        None,
        show_name=showName,
        out_name=f"[{flag}] $show$ - $ep${verstr} (BDRip 1920x1080 HEVC FLAC) [$crc32$]",
        mkv_title_naming=f"$show$ - $ep${verstr}",
        out_dir=out_dir,
        clean_work_dirs=False,
    )

    # Only check video files if not in dry-run mode
    video_file = None
    if RunMode.DRYRUN not in mode:
        video_search = GlobSearch(f"*{setup.episode}*.mkv", dir=dirPremux)
        if not video_search.paths:
            log.warn(
                f"Skipping episode {episode_number:02d}: Video file not found",
                mux_episode,
            )
            return None

        video_file = video_search.paths[0]
        setup.set_default_sub_timesource(video_file)

    premux = (
        None
        if RunMode.DRYRUN in mode
        else Premux(
            video_file,
            audio=None,
            subtitles=None,
            keep_attachments=False,
            mkvmerge_args=["--no-global-tags", "--no-chapters"],
        )
    )

    audio_search = GlobSearch(
        f"*{setup.episode}*.flac", allow_multiple=True, dir=dirAudio
    )
    audioFiles = AudioFile(audio_search.paths) if audio_search.paths else None

    # Find subtitle and audio files using the paths attribute
    sub_search = GlobSearch(f"*{setup.episode}*.ass", allow_multiple=True, dir=dirSub)
    subFiles = SubFile(sub_search.paths) if sub_search.paths else None

    # Check if required files exist
    if not subFiles:
        log.warn(
            f"Skipping episode {episode_number:02d}: Subtitle files missing",
            mux_episode,
        )
        return None

    if not audioFiles and RunMode.DRYRUN not in mode:
        log.warn(
            f"Skipping episode {episode_number:02d}: Audio files missing", mux_episode
        )
        return None

    subFiles.merge(
        f"./{setup.episode}/{setup.show_name} - {setup.episode}*TS*.ass",
    )
    subFiles.merge(
        f"./{setup.episode}/{setup.show_name} - {setup.episode}*OP*.ass",
        "opsync",
        "sync",
    )
    subFiles.merge(
        f"./{setup.episode}/{setup.show_name} - {setup.episode}*ED*.ass",
        "edsync",
        "sync",
    )
    subFiles.merge(r"./common/warning.ass").clean_garbage()
    chapters = Chapters.from_sub(subFiles, use_actor_field=True)
    fonts = subFiles.collect_fonts(use_system_fonts=False, additional_fonts="*")

    if RunMode.DRYRUN not in mode:
        try:
            # Perform the actual muxing
            outfile: Path = mux(
                premux,
                audioFiles.to_track("Japanese", "ja", default=True),
                subFiles.to_track(f"{flag}", "id", default=True),
                *fonts,
                chapters,
                tmdb=TmdbConfig(intTmdb, write_cover=True),
            )
            print(f"Successfully muxed: {outfile.name}")
            return outfile
        except Exception as e:
            log.error(
                f"Error muxing episode {episode_number:02d}: {str(e)}", mux_episode
            )
            return None
    else:
        log.debug(f"Dry run for episode {episode_number:02d} completed")
        return None


def parse_episode_list(episode_arg: str) -> List[int]:
    """
    Parse episode input into a list of episode numbers.

    Args:
        episode_arg: String containing episode selection (e.g., "1,3,5", "1-5", or "all")

    Returns:
        List of episode numbers to process

    Raises:
        ValueError: If the episode argument format is invalid
    """
    if episode_arg == "all":
        return []  # Empty list means process all episodes

    episodes = []
    # Split by comma and process each item
    for ep_item in episode_arg.split(","):
        ep_item = ep_item.strip()

        # Handle range notation (e.g., "1-5")
        if "-" in ep_item:
            range_parts = ep_item.split("-")
            if len(range_parts) != 2 or not all(
                part.strip().isdigit() for part in range_parts
            ):
                raise ValueError(f"Invalid episode range: {ep_item}")

            start = int(range_parts[0].strip())
            end = int(range_parts[1].strip())

            if start > end:
                raise ValueError(f"Invalid episode range (start > end): {ep_item}")

            episodes.extend(range(start, end + 1))

        # Handle single episode
        elif ep_item.isdigit():
            episodes.append(int(ep_item))
        else:
            raise ValueError(f"Invalid episode number: {ep_item}")

    return sorted(episodes)


def main() -> int:
    """
    Main function to parse arguments and control the muxing process.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parser = argparse.ArgumentParser(
        description="Anime muxing automation using MuxTools",
        epilog="Example: python script.py 1-5 output_dir -f MyGroup -v 2",
    )
    parser.add_argument(
        "episode",
        type=str,
        help='Episode(s) to mux: number, range (e.g., "1-5"), comma-separated list, or "all"',
    )
    parser.add_argument(
        "outdir",
        type=str,
        help="Output directory (default: muxed)",
        default="muxed",
        nargs="?",
    )
    parser.add_argument(
        "-v", "--version", type=int, default=1, help="Version number (default: 1)"
    )
    parser.add_argument(
        "-f", "--flag", default="testing", help="Group tag for filename"
    )
    parser.add_argument(
        "-d", "--dry-run", action="store_true", help="Testing without mux"
    )
    args = parser.parse_args()

    episode_arg: str = args.episode
    flag: str = args.flag
    mode = RunMode.NORMAL
    if args.dry_run:
        mode |= RunMode.DRYRUN
        log.info("Running in dry-run mode - no files will be created")

    try:
        # Create output directory if it doesn't exist
        Path(args.outdir).mkdir(exist_ok=True, parents=True)

        # Parse episode argument
        try:
            episode_numbers = parse_episode_list(episode_arg)
        except ValueError as e:
            log.error(str(e))
            return 2

        # If "all" was specified, find all available episodes
        if not episode_numbers and episode_arg == "all":
            episode_pattern = re.compile(r".*?(\d+).*")

            # Use the paths attribute instead of trying to iterate GlobSearch directly
            subtitle_search = GlobSearch(
                "*.ass", allow_multiple=True, recursive=True, dir=dirSub
            )

            # Extract episode numbers from subtitle filenames
            episode_numbers = sorted(
                {
                    int(match.group(1))
                    for f in subtitle_search.paths
                    if (match := episode_pattern.match(Path(f).stem))
                }
            )

            # Ensure we have at least one episode to process
            if not episode_numbers:
                log.error("No valid episodes found in subtitle directory.")
                return 1

            # If we want to limit the range, we can filter here
            max_episode = max(episode_numbers) if episode_numbers else 0
            log.info(f"Found episodes 1-{max_episode} in subtitle directory")

        # Ensure we have at least one episode to process
        if not episode_numbers:
            log.error("No valid episodes specified.")
            return 1

        # Mux the specified episodes
        successful_muxes = 0
        for ep in episode_numbers:
            result = mux_episode(
                ep, args.outdir, version=args.version, flag=flag, mode=mode
            )
            if result is not None or mode == RunMode.DRYRUN:
                successful_muxes += 1

        log.info(
            f"Muxing complete: {successful_muxes} of {len(episode_numbers)} episodes processed"
        )
        return 0 if successful_muxes > 0 else 1

    except LoggingException:
        log.crit("Critical error while muxing!")
        return 1

    except Exception as e:
        log.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
