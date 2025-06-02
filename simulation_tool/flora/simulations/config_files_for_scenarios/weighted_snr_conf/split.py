#!/usr/bin/env python3
"""
LoRa Debug Log File Splitter
============================
Splits large LoRa simulation debug log files into manageable chunks for analysis.
Specifically designed for debug_adr_opt_log files but works with any large text file.
"""

import os
import sys
from pathlib import Path

def get_file_info(filepath):
    """Get file size and line count information."""
    try:
        file_size = os.path.getsize(filepath)
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            line_count = sum(1 for _ in f)
        
        size_mb = file_size / (1024 * 1024)
        print(f"📄 {filepath}")
        print(f"   Size: {size_mb:.2f} MB ({file_size:,} bytes)")
        print(f"   Lines: {line_count:,}")
        return line_count, file_size
    except Exception as e:
        print(f"❌ Error reading {filepath}: {e}")
        return 0, 0

def split_into_chunks(filepath, chunk_size=500):
    """Split file into equal-sized chunks."""
    print(f"\n🔪 Splitting {filepath} into {chunk_size}-line chunks...")
    
    base_name = Path(filepath).stem
    chunk_count = 0
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as infile:
            while True:
                lines = []
                for _ in range(chunk_size):
                    line = infile.readline()
                    if not line:
                        break
                    lines.append(line)
                
                if not lines:
                    break
                
                chunk_filename = f"{base_name}_chunk_{chunk_count:02d}.txt"
                with open(chunk_filename, 'w', encoding='utf-8') as outfile:
                    outfile.writelines(lines)
                
                chunk_count += 1
                print(f"   ✅ Created: {chunk_filename} ({len(lines)} lines)")
                
                if len(lines) < chunk_size:
                    break
        
        print(f"   📊 Total chunks created: {chunk_count}")
        return chunk_count
        
    except Exception as e:
        print(f"❌ Error splitting {filepath}: {e}")
        return 0

def create_lora_analysis_samples(filepath, sample_size=500):
    """Create LoRa-specific analysis samples focusing on ADR decisions."""
    print(f"\n🔬 Creating LoRa ADR analysis samples from {filepath}...")
    
    base_name = Path(filepath).stem
    
    try:
        # Read all lines
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
        
        total_lines = len(all_lines)
        print(f"   📊 Total lines: {total_lines:,}")
        
        # Find interesting sections by looking for ADR keywords
        adr_lines = []
        init_lines = []
        decision_lines = []
        
        for i, line in enumerate(all_lines):
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in ['adr', 'evaluate', 'config', 'snr', 'weighted']):
                if i < total_lines * 0.1:  # First 10%
                    init_lines.append(i)
                elif 'decision' in line_lower or 'result' in line_lower or 'selected' in line_lower:
                    decision_lines.append(i)
                else:
                    adr_lines.append(i)
        
        # Create targeted samples
        samples = []
        
        # 1. Initialization sample
        samples.append((f"{base_name}_INIT.txt", all_lines[:sample_size], "initialization"))
        
        # 2. First ADR decisions
        if adr_lines:
            first_adr = max(0, adr_lines[0] - 50)
            samples.append((f"{base_name}_FIRST_ADR.txt", 
                          all_lines[first_adr:first_adr + sample_size], 
                          "first ADR decisions"))
        
        # 3. Middle ADR activity
        middle_start = max(0, (total_lines // 2) - (sample_size // 2))
        samples.append((f"{base_name}_MIDDLE_ADR.txt", 
                      all_lines[middle_start:middle_start + sample_size], 
                      "middle ADR activity"))
        
        # 4. Decision points
        if decision_lines:
            decision_start = max(0, decision_lines[0] - 25)
            samples.append((f"{base_name}_DECISIONS.txt", 
                          all_lines[decision_start:decision_start + sample_size], 
                          "key decisions"))
        
        # 5. End of simulation
        samples.append((f"{base_name}_END.txt", all_lines[-sample_size:], "final results"))
        
        # Write samples
        created_count = 0
        for filename, lines, description in samples:
            if lines:  # Only create if we have lines
                with open(filename, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                
                file_size_kb = os.path.getsize(filename) / 1024
                print(f"   ✅ {filename} ({len(lines)} lines, {file_size_kb:.1f} KB) - {description}")
                created_count += 1
        
        return created_count
        
    except Exception as e:
        print(f"❌ Error creating LoRa analysis samples from {filepath}: {e}")
        return 0

def create_analysis_samples(filepath, sample_size=500):
    """Create start, middle, and end samples for analysis."""
    print(f"\n📝 Creating analysis samples from {filepath}...")
    
    base_name = Path(filepath).stem
    
    try:
        # Read all lines
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
        
        total_lines = len(all_lines)
        print(f"   📊 Total lines: {total_lines:,}")
        
        # Calculate positions
        middle_start = max(0, (total_lines // 2) - (sample_size // 2))
        middle_end = min(total_lines, middle_start + sample_size)
        
        # Create samples
        samples = [
            (f"{base_name}_START.txt", all_lines[:sample_size], "first"),
            (f"{base_name}_MIDDLE.txt", all_lines[middle_start:middle_end], "middle"),
            (f"{base_name}_END.txt", all_lines[-sample_size:], "last")
        ]
        
        for filename, lines, position in samples:
            with open(filename, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            file_size_kb = os.path.getsize(filename) / 1024
            print(f"   ✅ {filename} ({len(lines)} lines, {file_size_kb:.1f} KB) - {position} {sample_size}")
        
        return len(samples)
        
    except Exception as e:
        print(f"❌ Error creating samples from {filepath}: {e}")
        return 0
    """Create start, middle, and end samples for analysis."""
    print(f"\n📝 Creating analysis samples from {filepath}...")
    
    base_name = Path(filepath).stem
    
    try:
        # Read all lines
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
        
        total_lines = len(all_lines)
        print(f"   📊 Total lines: {total_lines:,}")
        
        # Calculate positions
        middle_start = max(0, (total_lines // 2) - (sample_size // 2))
        middle_end = min(total_lines, middle_start + sample_size)
        
        # Create samples
        samples = [
            (f"{base_name}_START.txt", all_lines[:sample_size], "first"),
            (f"{base_name}_MIDDLE.txt", all_lines[middle_start:middle_end], "middle"),
            (f"{base_name}_END.txt", all_lines[-sample_size:], "last")
        ]
        
        for filename, lines, position in samples:
            with open(filename, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            file_size_kb = os.path.getsize(filename) / 1024
            print(f"   ✅ {filename} ({len(lines)} lines, {file_size_kb:.1f} KB) - {position} {sample_size}")
        
        return len(samples)
        
    except Exception as e:
        print(f"❌ Error creating samples from {filepath}: {e}")
        return 0

def create_quick_samples(filepaths, sample_size=500):
    """Create quick analysis samples from multiple files."""
    print(f"\n🚀 Creating quick analysis samples ({sample_size} lines each)...")
    
    sample_count = 0
    
    for i, filepath in enumerate(filepaths, 1):
        if not os.path.exists(filepath):
            print(f"⚠️  File not found: {filepath}")
            continue
            
        base_name = f"sample{i}"
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
            
            total_lines = len(all_lines)
            
            # Create 3 samples per file
            samples = [
                (f"{base_name}_first{sample_size}.txt", all_lines[:sample_size]),
                (f"{base_name}_middle{sample_size}.txt", all_lines[1000:1000+sample_size] if total_lines > 1000+sample_size else all_lines[total_lines//2:total_lines//2+sample_size]),
                (f"{base_name}_last{sample_size}.txt", all_lines[-sample_size:])
            ]
            
            for filename, lines in samples:
                if lines:  # Only create if we have lines
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.writelines(lines)
                    
                    file_size_kb = os.path.getsize(filename) / 1024
                    print(f"   ✅ {filename} ({len(lines)} lines, {file_size_kb:.1f} KB)")
                    sample_count += 1
        
        except Exception as e:
            print(f"❌ Error processing {filepath}: {e}")
    
    return sample_count

def find_log_files():
    """Find log files in current directory."""
    log_patterns = [
        'debug_adr_opt_log_WEIGHTED.txt',
        'debug_adr_opt_log_NO_WEIGHT.txt',
        'part1', 'part2', 'part1.txt', 'part2.txt'
    ]
    
    files_found = []
    for pattern in log_patterns:
        if os.path.exists(pattern):
            files_found.append(pattern)
    
    # Also look for any .txt files > 1MB
    for item in os.listdir('.'):
        if (item.endswith('.txt') and 
            os.path.isfile(item) and 
            os.path.getsize(item) > 1024*1024 and  # > 1MB
            item not in files_found):
            files_found.append(item)
    
    return files_found

def main():
    """Main function with interactive menu."""
    print("=" * 60)
    print("🔧 LoRa DEBUG LOG FILE SPLITTER")
    print("=" * 60)
    
    # Check for files
    files_to_process = find_log_files()
    
    if not files_to_process:
        print("❌ No large log files found!")
        print("📁 Looking for:")
        print("   - debug_adr_opt_log_WEIGHTED.txt")
        print("   - debug_adr_opt_log_NO_WEIGHT.txt") 
        print("   - part1, part2")
        print("   - Any .txt files > 1MB")
        print("\n📁 Current directory contents:")
        for item in os.listdir('.'):
            if os.path.isfile(item) and item.endswith('.txt'):
                size_mb = os.path.getsize(item) / (1024 * 1024)
                print(f"   {item} ({size_mb:.2f} MB)")
        
        # Allow manual file input
        manual_file = input("\n📝 Enter filename manually (or press Enter to exit): ").strip()
        if manual_file and os.path.exists(manual_file):
            files_to_process = [manual_file]
        else:
            return
    
    # Show file information
    print("\n📋 FILES FOUND:")
    for filepath in files_to_process:
        get_file_info(filepath)
    
    # Interactive menu
    print("\n" + "=" * 60)
    print("🎯 LoRa LOG SPLITTING OPTIONS:")
    print("=" * 60)
    print("1. 🚀 Quick Analysis Samples (RECOMMENDED)")
    print("   Creates 6 small files perfect for comparing WEIGHTED vs NO_WEIGHT")
    print("   Format: sample1_first500.txt, sample2_middle500.txt, etc.")
    print()
    print("2. 🔬 LoRa ADR-Focused Analysis") 
    print("   Creates targeted samples focusing on ADR decisions and configurations")
    print("   Perfect for debugging weighted SNR vs non-weighted SNR differences!")
    print()
    print("3. 📝 Standard Analysis Samples")
    print("   Creates START, MIDDLE, END files for each input file")
    print()
    print("4. 🔪 Split into Equal Chunks") 
    print("   Splits each file into many small chunks of equal size")
    print()
    print("5. ⚙️  Custom Sample Size")
    print("   Choose your own sample size for any of the above options")
    print()
    
    try:
        choice = input("👆 Choose option (1-5): ").strip()
        
        if choice == '1':
            # Quick samples - RECOMMENDED for comparison
            sample_count = create_quick_samples(files_to_process, 500)
            print(f"\n🎉 SUCCESS! Created {sample_count} analysis files")
            print("📤 Perfect for comparing WEIGHTED vs NO_WEIGHT algorithms!")
            print("📤 Share: sample1_first500.txt (WEIGHTED) vs sample2_first500.txt (NO_WEIGHT)")
            
        elif choice == '2':
            # LoRa ADR-focused analysis
            total_samples = 0
            for filepath in files_to_process:
                total_samples += create_lora_analysis_samples(filepath, 500)
            print(f"\n🎉 SUCCESS! Created {total_samples} LoRa ADR analysis files")
            print("📤 Focus on *_DECISIONS.txt and *_FIRST_ADR.txt files for best insights!")
            
        elif choice == '3':
            # Standard analysis samples
            total_samples = 0
            for filepath in files_to_process:
                total_samples += create_analysis_samples(filepath, 500)
            print(f"\n🎉 SUCCESS! Created {total_samples} standard analysis files")
            
        elif choice == '4':
            # Split into chunks
            chunk_size = int(input("📏 Lines per chunk (default 500): ") or 500)
            total_chunks = 0
            for filepath in files_to_process:
                total_chunks += split_into_chunks(filepath, chunk_size)
            print(f"\n🎉 SUCCESS! Created {total_chunks} chunk files")
            
        elif choice == '5':
            # Custom sample size
            sample_size = int(input("📏 Sample size in lines (default 500): ") or 500)
            sub_choice = input("Choose method (1=Quick, 2=LoRa-focused, 3=Standard): ").strip()
            
            if sub_choice == '1':
                sample_count = create_quick_samples(files_to_process, sample_size)
            elif sub_choice == '2':
                sample_count = sum(create_lora_analysis_samples(f, sample_size) for f in files_to_process)
            else:
                sample_count = sum(create_analysis_samples(f, sample_size) for f in files_to_process)
            
            print(f"\n🎉 SUCCESS! Created {sample_count} analysis files")
            
        else:
            print("❌ Invalid choice. Run script again.")
            return
        
        # Show results
        print("\n📁 CREATED FILES:")
        current_files = sorted([f for f in os.listdir('.') if f.endswith('.txt') and os.path.getsize(f) < 1024*1024])  # Files under 1MB
        for filename in current_files:
            size_kb = os.path.getsize(filename) / 1024
            if size_kb < 200:  # Only show small files suitable for sharing
                print(f"   ✅ {filename} ({size_kb:.1f} KB)")
        
    except KeyboardInterrupt:
        print("\n\n👋 Cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()