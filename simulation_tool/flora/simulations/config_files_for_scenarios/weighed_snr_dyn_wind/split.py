#!/usr/bin/env python3
"""
Log File Splitter Script
Splits large log files into smaller, manageable chunks
"""

import os
import sys
import argparse
from pathlib import Path

def split_by_lines(input_file, lines_per_chunk=1000, output_prefix="chunk"):
    """Split file by number of lines"""
    print(f"Splitting {input_file} by {lines_per_chunk} lines per chunk...")
    
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        chunk_num = 1
        output_file = None
        
        for line_num, line in enumerate(f, 1):
            # Start new chunk
            if (line_num - 1) % lines_per_chunk == 0:
                if output_file:
                    output_file.close()
                
                output_filename = f"{output_prefix}_{chunk_num:03d}.txt"
                output_file = open(output_filename, 'w', encoding='utf-8')
                print(f"Creating {output_filename}...")
                chunk_num += 1
            
            output_file.write(line)
        
        if output_file:
            output_file.close()
    
    print(f"Split complete! Created {chunk_num-1} chunks.")

def split_by_size(input_file, size_mb=1, output_prefix="chunk"):
    """Split file by size in MB"""
    print(f"Splitting {input_file} by {size_mb}MB per chunk...")
    
    size_bytes = size_mb * 1024 * 1024
    chunk_num = 1
    current_size = 0
    output_file = None
    
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # Start new chunk if size limit reached
            if current_size >= size_bytes:
                if output_file:
                    output_file.close()
                
                output_filename = f"{output_prefix}_{chunk_num:03d}.txt"
                output_file = open(output_filename, 'w', encoding='utf-8')
                print(f"Creating {output_filename}...")
                chunk_num += 1
                current_size = 0
            
            # Create first file if needed
            if output_file is None:
                output_filename = f"{output_prefix}_{chunk_num:03d}.txt"
                output_file = open(output_filename, 'w', encoding='utf-8')
                print(f"Creating {output_filename}...")
                chunk_num += 1
            
            output_file.write(line)
            current_size += len(line.encode('utf-8'))
        
        if output_file:
            output_file.close()
    
    print(f"Split complete! Created {chunk_num-1} chunks.")

def split_by_adr_blocks(input_file, output_prefix="adr_block"):
    """Split file by ADR evaluation blocks"""
    print(f"Splitting {input_file} by ADR evaluation blocks...")
    
    chunk_num = 1
    output_file = None
    current_block = []
    in_adr_block = False
    
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # Detect start of ADR block
            if "===== [DEBUG START] evaluateADR" in line:
                # Save previous block if exists
                if current_block and output_file:
                    output_file.close()
                
                # Start new block
                output_filename = f"{output_prefix}_{chunk_num:03d}.txt"
                output_file = open(output_filename, 'w', encoding='utf-8')
                print(f"Creating {output_filename}...")
                chunk_num += 1
                in_adr_block = True
                current_block = [line]
                output_file.write(line)
            
            # Continue current block
            elif in_adr_block:
                current_block.append(line)
                output_file.write(line)
                
                # End of ADR block
                if "===== [DEBUG END] evaluateADR" in line:
                    in_adr_block = False
            
            # Lines outside ADR blocks - add to current file if exists
            elif output_file:
                output_file.write(line)
    
    if output_file:
        output_file.close()
    
    print(f"Split complete! Created {chunk_num-1} ADR blocks.")

def extract_important_sections(input_file, output_file="important_sections.txt"):
    """Extract only important sections from log"""
    print(f"Extracting important sections from {input_file}...")
    
    important_patterns = [
        "[DEBUG START] evaluateADR",
        "[DEBUG END] evaluateADR", 
        "[DEBUG START] chooseBestConfiguration",
        "[DEBUG END] chooseBestConfiguration",
        "[SUMMARY] Found",
        "[RESULT] Selected Config:",
        "[DATA] PERcurrent",
        "[CHECK] SF=",
        "BIAS] SF=",
        "Testing SF="
    ]
    
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as infile, \
         open(output_file, 'w', encoding='utf-8') as outfile:
        
        extracted_lines = 0
        for line in infile:
            if any(pattern in line for pattern in important_patterns):
                outfile.write(line)
                extracted_lines += 1
    
    print(f"Extracted {extracted_lines} important lines to {output_file}")

def get_file_info(input_file):
    """Display file information"""
    if not os.path.exists(input_file):
        print(f"Error: File {input_file} not found!")
        return
    
    file_size = os.path.getsize(input_file)
    file_size_mb = file_size / (1024 * 1024)
    
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        line_count = sum(1 for _ in f)
    
    print(f"\n📊 FILE INFO:")
    print(f"File: {input_file}")
    print(f"Size: {file_size_mb:.2f} MB ({file_size:,} bytes)")
    print(f"Lines: {line_count:,}")
    print(f"Avg bytes per line: {file_size/line_count:.1f}")

def main():
    parser = argparse.ArgumentParser(description="Split large log files into smaller chunks")
    parser.add_argument("input_file", help="Input log file to split")
    parser.add_argument("-m", "--method", choices=["lines", "size", "adr", "extract"], 
                       default="lines", help="Split method (default: lines)")
    parser.add_argument("-l", "--lines", type=int, default=1000, 
                       help="Lines per chunk (default: 1000)")
    parser.add_argument("-s", "--size", type=float, default=1.0, 
                       help="Size per chunk in MB (default: 1.0)")
    parser.add_argument("-p", "--prefix", default="chunk", 
                       help="Output file prefix (default: chunk)")
    parser.add_argument("-i", "--info", action="store_true", 
                       help="Show file info only")
    
    args = parser.parse_args()
    
    # Check if file exists
    if not os.path.exists(args.input_file):
        print(f"❌ Error: File '{args.input_file}' not found!")
        sys.exit(1)
    
    # Show file info
    get_file_info(args.input_file)
    
    if args.info:
        return
    
    print(f"\n🔧 SPLITTING METHOD: {args.method}")
    
    # Split based on method
    if args.method == "lines":
        split_by_lines(args.input_file, args.lines, args.prefix)
    elif args.method == "size":
        split_by_size(args.input_file, args.size, args.prefix)
    elif args.method == "adr":
        split_by_adr_blocks(args.input_file, args.prefix)
    elif args.method == "extract":
        extract_important_sections(args.input_file, f"{args.prefix}_important.txt")
    
    print("\n✅ Done!")

if __name__ == "__main__":
    main()