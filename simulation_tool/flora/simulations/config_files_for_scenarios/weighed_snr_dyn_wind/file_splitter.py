#!/usr/bin/env python3
"""
Script pentru împărțirea fișierelor TXT în bucăți de maxim 30MB
Autor: Claude
"""

import os
import sys
import argparse
from pathlib import Path

def format_size(size_bytes):
    """Formatează dimensiunea în bytes într-un format citibil"""
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f}{size_names[i]}"

def split_file(input_file, max_size_mb=30, output_dir=None):
    """
    Împarte un fișier în bucăți de dimensiune maximă specificată
    
    Args:
        input_file (str): Calea către fișierul de intrare
        max_size_mb (int): Dimensiunea maximă în MB pentru fiecare bucată
        output_dir (str): Directorul pentru fișierele de ieșire
    """
    # Convertește MB în bytes
    max_size_bytes = max_size_mb * 1024 * 1024
    
    # Verifică dacă fișierul există
    if not os.path.exists(input_file):
        print(f"❌ Eroare: Fișierul '{input_file}' nu există!")
        return False
    
    # Obține informații despre fișier
    file_size = os.path.getsize(input_file)
    print(f"📁 Fișier de intrare: {input_file}")
    print(f"📏 Dimensiune: {format_size(file_size)}")
    print(f"✂️ Dimensiune maximă per bucată: {max_size_mb}MB")
    
    # Dacă fișierul este deja mai mic decât limita
    if file_size <= max_size_bytes:
        print(f"✅ Fișierul este deja mai mic de {max_size_mb}MB. Nu este necesară împărțirea.")
        return True
    
    # Pregătește directorul de ieșire
    input_path = Path(input_file)
    if output_dir is None:
        output_dir = input_path.parent / f"{input_path.stem}_split"
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(exist_ok=True)
    print(f"📂 Director de ieșire: {output_dir}")
    
    # Calculează numărul estimat de bucăți
    estimated_parts = (file_size + max_size_bytes - 1) // max_size_bytes
    print(f"🔢 Numărul estimat de bucăți: {estimated_parts}")
    print("─" * 50)
    
    part_number = 1
    total_bytes_written = 0
    
    try:
        with open(input_file, 'r', encoding='utf-8') as infile:
            while True:
                # Generează numele fișierului de ieșire
                output_filename = f"{input_path.stem}_part_{part_number:03d}.txt"
                output_path = output_dir / output_filename
                
                print(f"📝 Creez bucata {part_number}: {output_filename}")
                
                bytes_written_this_part = 0
                lines_written = 0
                
                with open(output_path, 'w', encoding='utf-8') as outfile:
                    while bytes_written_this_part < max_size_bytes:
                        line = infile.readline()
                        
                        # Sfârșitul fișierului
                        if not line:
                            break
                        
                        line_bytes = len(line.encode('utf-8'))
                        
                        # Verifică dacă adăugarea acestei linii ar depăși limita
                        if bytes_written_this_part + line_bytes > max_size_bytes and bytes_written_this_part > 0:
                            # Pune linia înapoi în stream (simulat prin seek)
                            infile.seek(infile.tell() - len(line))
                            break
                        
                        outfile.write(line)
                        bytes_written_this_part += line_bytes
                        lines_written += 1
                
                total_bytes_written += bytes_written_this_part
                
                print(f"   ✅ {format_size(bytes_written_this_part)} | {lines_written:,} linii")
                
                # Verifică dacă am ajuns la sfârșitul fișierului
                if bytes_written_this_part == 0:
                    # Șterge fișierul gol
                    os.remove(output_path)
                    break
                
                part_number += 1
                
                # Verifică dacă mai sunt date de citit
                current_pos = infile.tell()
                infile.seek(0, 2)  # Mergi la sfârșitul fișierului
                end_pos = infile.tell()
                infile.seek(current_pos)  # Întoarce-te la poziția curentă
                
                if current_pos >= end_pos:
                    break
    
    except Exception as e:
        print(f"❌ Eroare în timpul împărțirii: {e}")
        return False
    
    print("─" * 50)
    print(f"✅ Împărțire completă!")
    print(f"📊 Total bucăți create: {part_number - 1}")
    print(f"📏 Total bytes procesați: {format_size(total_bytes_written)}")
    print(f"📂 Fișierele sunt salvate în: {output_dir}")
    
    return True

def main():
    parser = argparse.ArgumentParser(
        description="Împarte un fișier TXT în bucăți de dimensiune maximă specificată",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemple de utilizare:
  python file_splitter.py input.txt                    # Split în bucăți de 30MB
  python file_splitter.py input.txt -s 50             # Split în bucăți de 50MB
  python file_splitter.py input.txt -o ./output       # Specifică directorul de ieșire
  python file_splitter.py large_file.txt -s 10 -o ./splits
        """
    )
    
    parser.add_argument(
        'input_file',
        help='Fișierul TXT de împărțit'
    )
    
    parser.add_argument(
        '-s', '--size',
        type=int,
        default=30,
        help='Dimensiunea maximă în MB pentru fiecare bucată (default: 30MB)'
    )
    
    parser.add_argument(
        '-o', '--output',
        help='Directorul pentru fișierele de ieșire (default: <nume_fisier>_split/)'
    )
    
    args = parser.parse_args()
    
    # Validări
    if args.size <= 0:
        print("❌ Eroare: Dimensiunea trebuie să fie pozitivă!")
        sys.exit(1)
    
    if args.size > 1000:
        response = input(f"⚠️ Dimensiunea de {args.size}MB este foarte mare. Continuați? (y/N): ")
        if response.lower() not in ['y', 'yes']:
            print("Operațiune anulată.")
            sys.exit(0)
    
    print("🚀 Pornesc împărțirea fișierului...")
    print("=" * 60)
    
    success = split_file(args.input_file, args.size, args.output)
    
    if success:
        print("=" * 60)
        print("🎉 Operațiune completată cu succes!")
    else:
        print("💥 Operațiune eșuată!")
        sys.exit(1)

if __name__ == "__main__":
    main()