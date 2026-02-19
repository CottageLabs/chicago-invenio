#!/usr/bin/env python3
"""Verify file checksums from MARCXML 856$c against local files."""

import xml.etree.ElementTree as ET
import sys
import argparse
import hashlib
import os
from urllib.parse import unquote

NS = "{http://www.loc.gov/MARC21/slim}"


def md5sum(filepath):
    """Compute MD5 checksum of a file."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksums(input_file, files_dir):
    """Verify checksums from MARCXML 856.4 subfield c against local files.

    Args:
        input_file: Path to MARCXML file containing checksums
        files_dir: Path to local directory containing files to verify
    """
    tree = ET.parse(input_file)
    root = tree.getroot()

    all_records = root.findall(f".//{NS}record")
    total_records = len(all_records)

    records_with_checksum = 0
    matched = 0
    mismatched = 0
    missing_files = 0
    no_checksum = 0
    no_url = 0

    mismatched_details = []
    missing_details = []

    for i, record in enumerate(all_records, 1):
        print(f"\rProcessing record {i}/{total_records} ...", end="", flush=True)

        control_field = record.find(f".//{NS}controlfield[@tag='001']")
        record_id = control_field.text if control_field is not None else "No ID"

        for datafield in record.findall(f".//{NS}datafield[@tag='856']"):
            if datafield.get("ind1") != "4":
                continue

            # Extract checksum from subfield c
            checksum_sf = datafield.find(f".//{NS}subfield[@code='c']")
            if checksum_sf is None or not checksum_sf.text:
                no_checksum += 1
                continue

            expected_checksum = checksum_sf.text.strip()
            records_with_checksum += 1

            # Extract filename from subfield u
            url_sf = datafield.find(f".//{NS}subfield[@code='u']")
            if url_sf is None or not url_sf.text:
                no_url += 1
                continue

            url = url_sf.text.strip()
            filename = unquote(url.rsplit("/", 1)[-1])
            filepath = os.path.join(files_dir, record_id, filename)

            if not os.path.isfile(filepath):
                missing_files += 1
                missing_details.append(
                    {"record_id": record_id, "filename": filename}
                )
                continue

            actual_checksum = md5sum(filepath)
            if actual_checksum == expected_checksum:
                matched += 1
            else:
                mismatched += 1
                mismatched_details.append(
                    {
                        "record_id": record_id,
                        "filename": filename,
                        "expected": expected_checksum,
                        "actual": actual_checksum,
                    }
                )

    # Clear the progress line
    print("\r" + " " * 50 + "\r", end="", flush=True)

    # Summary
    print("=" * 60)
    print("CHECKSUM VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total records:              {total_records}")
    print(f"856.4 fields with checksum: {records_with_checksum}")
    print(f"856.4 fields without checksum (subfield c): {no_checksum}")
    print(f"856.4 fields without URL (subfield u):      {no_url}")
    print()
    print(f"Matched:       {matched}")
    print(f"Mismatched:    {mismatched}")
    print(f"Missing files: {missing_files}")

    if mismatched_details:
        print()
        print("MISMATCHED CHECKSUMS:")
        print("-" * 60)
        for d in mismatched_details:
            print(f"  Record {d['record_id']}: {d['filename']}")
            print(f"    expected: {d['expected']}")
            print(f"    actual:   {d['actual']}")

    if missing_details:
        print()
        print(f"MISSING FILES ({missing_files}):")
        print("-" * 60)
        for d in missing_details:
            print(f"  Record {d['record_id']}: {d['filename']}")

    if mismatched == 0 and missing_files == 0 and records_with_checksum > 0:
        print()
        print("All checksums verified successfully.")

    return mismatched == 0 and missing_files == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify file checksums from MARCXML 856$c against local files"
    )
    parser.add_argument(
        "files_dir",
        help="Directory containing local files to verify",
    )
    parser.add_argument(
        "input_file",
        help="Input MARCXML file with checksums",
    )

    args = parser.parse_args()

    if not os.path.isdir(args.files_dir):
        print(f"Error: {args.files_dir} is not a directory")
        sys.exit(1)

    try:
        ok = verify_checksums(args.input_file, args.files_dir)
        sys.exit(0 if ok else 1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
