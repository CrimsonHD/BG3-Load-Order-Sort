import struct
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from pathlib import Path
import json
import os

try:
    import lz4.frame
    import lz4.block
    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False
    print("Warning: lz4 library not found. Install with: pip install lz4")


@dataclass
class ModMetadata:
    """Container for BG3 mod metadata"""
    name: str = ""
    description: str = ""
    author: str = ""
    version: str = ""
    uuid: str = ""
    folder: str = ""
    dependencies: List[Dict[str, str]] = None
    conflicts: List[Dict[str, str]] = None
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []
        if self.conflicts is None:
            self.conflicts = []


@dataclass 
class PackageHeader:
    """PAK file header information"""
    signature: int
    version: int
    file_list_offset: int
    file_list_size: int
    num_files: int
    data_offset: int = 0


@dataclass
class FileEntry:
    """Entry for a file within the PAK"""
    name: str
    offset: int
    size_on_disk: int
    uncompressed_size: int
    archive_part: int = 0
    flags: int = 0


class BG3PakReader:
    """Reader for BG3 PAK files using LSLib-compatible logic"""
    
    LSPK_SIGNATURE = 0x4B50534C  # 'LSPK'
    
    def __init__(self, pak_path: str):
        self.pak_path = Path(pak_path)
        self.header: Optional[PackageHeader] = None
        self.files: List[FileEntry] = []
        
    def _read_header_v13_plus(self, data: bytes) -> PackageHeader:
        """Read header for PAK version 13+ (header at end of file)"""
        if len(data) < 12:
            raise ValueError("File too small for v13+ header")
            
        # Read header size and signature from end of file
        header_size = struct.unpack('<I', data[-8:-4])[0]
        signature = struct.unpack('<I', data[-4:])[0]
        
        if signature != self.LSPK_SIGNATURE:
            raise ValueError(f"Invalid PAK signature: 0x{signature:08X}")
            
        # Calculate header offset
        header_offset = len(data) - header_size
        if header_offset < 0:
            raise ValueError("Invalid header size")
            
        header_data = data[header_offset:-8]  # Exclude the size and signature we already read
        
        if len(header_data) < 28:
            raise ValueError("Header data too small")
        
        # Parse header structure for v13+
        version = struct.unpack('<I', header_data[0:4])[0]
        file_list_offset = struct.unpack('<Q', header_data[4:12])[0]
        file_list_size = struct.unpack('<I', header_data[12:16])[0]
        # Skip 4 bytes (padding/flags)
        num_files = struct.unpack('<I', header_data[20:24])[0]
        
        return PackageHeader(
            signature=signature,
            version=version,
            file_list_offset=file_list_offset,
            file_list_size=file_list_size,
            num_files=num_files,
            data_offset=0  # For v13+, data starts at beginning
        )
    
    def _read_header_v10(self, data: bytes) -> PackageHeader:
        """Read header for PAK version 10 (header at beginning)"""
        if len(data) < 32:
            raise ValueError("File too small for v10 header")
            
        signature = struct.unpack('<I', data[0:4])[0]
        if signature != self.LSPK_SIGNATURE:
            raise ValueError(f"Invalid PAK signature: 0x{signature:08X}")
            
        version = struct.unpack('<I', data[4:8])[0]
        file_list_offset = struct.unpack('<Q', data[8:16])[0]
        file_list_size = struct.unpack('<I', data[16:20])[0]
        # Skip 8 bytes
        num_files = struct.unpack('<I', data[28:32])[0]
        
        return PackageHeader(
            signature=signature,
            version=version,
            file_list_offset=file_list_offset,
            file_list_size=file_list_size,
            num_files=num_files,
            data_offset=280  # Fixed offset for v10
        )
    
    def _decompress_data(self, compressed_data: bytes, expected_size: int = 0) -> bytes:
        """Decompress LZ4-compressed data with improved error handling"""
        if not HAS_LZ4:
            raise ImportError("lz4 library required for decompression")
        
        # Try different LZ4 decompression methods
        methods = [
            ("frame", lambda: lz4.frame.decompress(compressed_data)),
            ("block_with_size", lambda: lz4.block.decompress(compressed_data, uncompressed_size=expected_size) if expected_size > 0 else None),
            ("block_auto", lambda: lz4.block.decompress(compressed_data))
        ]
        
        for method_name, decompress_func in methods:
            try:
                result = decompress_func()
                if result is not None:
                    print(f"Successfully decompressed using {method_name} method")
                    return result
            except Exception as e:
                print(f"Decompression method {method_name} failed: {e}")
                continue
        
        # If all methods fail, check if it's already decompressed
        try:
            # Try to decode as UTF-8 to see if it's already text
            test_decode = compressed_data.decode('utf-8')
            print("Data appears to be already decompressed")
            return compressed_data
        except UnicodeDecodeError:
            pass
        
        raise Exception("All decompression methods failed")
    
    def _debug_entry_structure(self, entry_data: bytes, entry_index: int):
        """Debug helper to examine entry structure"""
        print(f"\nDebugging entry {entry_index} structure:")
        print(f"Entry data length: {len(entry_data)}")
        
        # Show first part as hex for structure analysis
        hex_data = ' '.join(f'{b:02x}' for b in entry_data[:64])
        print(f"First 64 bytes (hex): {hex_data}")
        
        # Try different offset interpretations
        for name_size in [256, 260, 264]:
            if len(entry_data) >= name_size + 16:
                try:
                    name_bytes = entry_data[0:name_size]
                    null_pos = name_bytes.find(b'\x00')
                    if null_pos >= 0:
                        name = name_bytes[:null_pos].decode('utf-8', errors='ignore')
                    else:
                        name = name_bytes[:50].decode('utf-8', errors='ignore') + "..."
                    
                    # Try different offset positions
                    for offset_pos in range(name_size, min(name_size + 16, len(entry_data) - 8), 4):
                        try:
                            offset_val = struct.unpack('<Q', entry_data[offset_pos:offset_pos + 8])[0]
                            size_val = struct.unpack('<I', entry_data[offset_pos + 8:offset_pos + 12])[0] if offset_pos + 12 <= len(entry_data) else 0
                            print(f"  Name size {name_size}, offset pos {offset_pos}: '{name[:30]}...' offset={offset_val}, size={size_val}")
                        except:
                            pass
                except:
                    pass

    def _read_file_entries(self, data: bytes) -> List[FileEntry]:
        """Read file entries from PAK"""
        entries = []
        
        if not self.header:
            return entries
            
        try:
            # Read the file list
            file_list_start = self.header.file_list_offset
            
            if file_list_start + 8 > len(data):
                print("File list offset beyond file size")
                return entries
            
            # Read number of files and compressed size
            num_files = struct.unpack('<I', data[file_list_start:file_list_start + 4])[0]
            compressed_size = struct.unpack('<I', data[file_list_start + 4:file_list_start + 8])[0]
            
            print(f"Files: {num_files}, Compressed size: {compressed_size}")
            
            # Read compressed file list data
            compressed_start = file_list_start + 8
            if compressed_start + compressed_size > len(data):
                print("Compressed data extends beyond file")
                return entries
                
            compressed_data = data[compressed_start:compressed_start + compressed_size]
            
            # Decompress the file list with expected size
            expected_decompressed_size = num_files * 300  # Conservative estimate
            try:
                decompressed = self._decompress_data(compressed_data, expected_decompressed_size)
                print(f"Decompressed size: {len(decompressed)}")
            except Exception as e:
                print(f"Decompression failed: {e}")
                return entries
            
            # Determine entry size based on version and actual data
            calculated_entry_size = len(decompressed) // num_files if num_files > 0 else 0
            print(f"Calculated entry size from data: {calculated_entry_size}")
            
            # Use calculated size or fall back to version-based
            if calculated_entry_size > 250 and calculated_entry_size < 350:
                entry_size = calculated_entry_size
            else:
                # Version-based fallback
                if self.header.version >= 18:
                    entry_size = 296  # Try 296 for v18
                elif self.header.version >= 15:
                    entry_size = 296
                elif self.header.version >= 13:
                    entry_size = 296
                else:
                    entry_size = 272
            
            print(f"Using entry size: {entry_size}")
            
            # Debug the first entry structure
            if len(decompressed) >= entry_size:
                self._debug_entry_structure(decompressed[:entry_size], 0)
            
            offset = 0
            for i in range(min(num_files, len(decompressed) // entry_size)):
                if offset + entry_size > len(decompressed):
                    print(f"Entry {i}: Not enough data remaining")
                    break
                    
                entry_data = decompressed[offset:offset + entry_size]
                
                try:
                    # Try different name field sizes for v18
                    name = ""
                    file_offset = 0
                    size_on_disk = 0
                    uncompressed_size = 0
                    archive_part = 0
                    flags = 0
                    
                    # For version 18, use the correct structure
                    if self.header.version >= 18:
                        # Version 18 uses: 256-byte name + 32-bit offset + 32-bit size_on_disk + 32-bit uncompressed_size
                        name_bytes = entry_data[0:256]
                        null_pos = name_bytes.find(b'\x00')
                        if null_pos >= 0:
                            name = name_bytes[:null_pos].decode('utf-8', errors='ignore')
                        
                        # Structure is: name(256) + offset(4) + size_on_disk(4) + uncompressed_size(4) + other fields
                        file_offset = struct.unpack('<I', entry_data[256:260])[0]
                        size_on_disk = struct.unpack('<I', entry_data[264:268])[0]  # 32-bit size
                        uncompressed_size = struct.unpack('<I', entry_data[268:272])[0]  # 32-bit uncompressed size
                        
                        # Additional fields if available
                        if len(entry_data) >= 272:
                            archive_part = struct.unpack('<I', entry_data[268:272])[0]
                                
                    else:
                        # Standard parsing for older versions
                        name_bytes = entry_data[0:256]
                        null_pos = name_bytes.find(b'\x00')
                        if null_pos >= 0:
                            name = name_bytes[:null_pos].decode('utf-8', errors='ignore')
                        
                        if self.header.version >= 13:
                            file_offset = struct.unpack('<Q', entry_data[256:264])[0]
                            size_on_disk = struct.unpack('<Q', entry_data[264:272])[0]
                            uncompressed_size = struct.unpack('<Q', entry_data[272:280])[0]
                            if len(entry_data) >= 284:
                                archive_part = struct.unpack('<I', entry_data[280:284])[0]
                            if len(entry_data) >= 288:
                                flags = struct.unpack('<I', entry_data[284:288])[0]
                        else:
                            file_offset = struct.unpack('<Q', entry_data[256:264])[0]
                            size_on_disk = struct.unpack('<I', entry_data[264:268])[0]
                            uncompressed_size = struct.unpack('<I', entry_data[268:272])[0]
                    
                    if name and file_offset > 0:  # Only add entries with valid names and offsets
                        entries.append(FileEntry(
                            name=name,
                            offset=file_offset,
                            size_on_disk=size_on_disk,
                            uncompressed_size=uncompressed_size,
                            archive_part=archive_part,
                            flags=flags
                        ))
                        
                        if i < 5:  # Debug first few entries
                            print(f"Entry {i}: {name} (offset: {file_offset}, size: {size_on_disk})")
                
                except Exception as e:
                    print(f"Error parsing entry {i}: {e}")
                    continue
                    
                offset += entry_size
                
        except Exception as e:
            print(f"Error reading file entries: {e}")
        
        return entries
    
    def read_pak_structure(self) -> bool:
        """Read the PAK file structure"""
        try:
            with open(self.pak_path, 'rb') as f:
                data = f.read()
            
            print(f"File size: {len(data)} bytes")
            
            if len(data) < 12:
                print("File too small")
                return False
            
            # Check signature at beginning (v10) vs end (v13+)
            start_sig = struct.unpack('<I', data[0:4])[0] if len(data) >= 4 else 0
            end_sig = struct.unpack('<I', data[-4:])[0] if len(data) >= 4 else 0
            
            print(f"Start signature: 0x{start_sig:08X}, End signature: 0x{end_sig:08X}")
            
            # Try v13+ header first (more common for BG3)
            if end_sig == self.LSPK_SIGNATURE:
                try:
                    self.header = self._read_header_v13_plus(data)
                    print(f"Successfully read v13+ header (version {self.header.version})")
                except Exception as e:
                    print(f"Failed to read v13+ header: {e}")
                    self.header = None
            
            # Try v10 header if v13+ failed
            if not self.header and start_sig == self.LSPK_SIGNATURE:
                try:
                    self.header = self._read_header_v10(data)
                    print(f"Successfully read v10 header (version {self.header.version})")
                except Exception as e:
                    print(f"Failed to read v10 header: {e}")
                    return False
            
            if not self.header:
                print("Could not read any valid header")
                return False
            
            # Read file entries
            self.files = self._read_file_entries(data)
            print(f"Read {len(self.files)} file entries")
            
            return len(self.files) > 0
            
        except Exception as e:
            print(f"Error reading PAK structure: {e}")
            return False
    
    def extract_file(self, filename: str) -> Optional[bytes]:
        """Extract a specific file from the PAK"""
        if not self.header or not self.files:
            if not self.read_pak_structure():
                return None
        
        # Find the file (case-insensitive)
        target_file = None
        for file_entry in self.files:
            if file_entry.name.lower() == filename.lower():
                target_file = file_entry
                break
        
        if not target_file:
            print(f"File not found: {filename}")
            return None
        
        try:
            with open(self.pak_path, 'rb') as f:
                # Calculate actual offset
                actual_offset = target_file.offset
                if self.header.version < 13:
                    actual_offset += self.header.data_offset
                
                f.seek(actual_offset)
                file_data = f.read(target_file.size_on_disk)
                
                if len(file_data) != target_file.size_on_disk:
                    print(f"Warning: Read {len(file_data)} bytes, expected {target_file.size_on_disk}")
                
                # FIXED: Always attempt decompression if sizes differ, or if file looks compressed
                if HAS_LZ4:
                    # Check if decompression is needed
                    needs_decompression = False
                    
                    # Method 1: Size difference indicates compression
                    if (target_file.size_on_disk != target_file.uncompressed_size and 
                        target_file.uncompressed_size > 0):
                        needs_decompression = True
                        print(f"Size difference detected: {target_file.size_on_disk} vs {target_file.uncompressed_size}")
                    
                    # Method 2: Check for LZ4 magic bytes or binary patterns
                    if not needs_decompression and len(file_data) > 4:
                        # Common LZ4 frame magic: 0x184D2204
                        if file_data[:4] == b'\x04\x22\x4D\x18':
                            needs_decompression = True
                            print("LZ4 frame magic detected")
                        # Or check for high entropy/binary data that might be compressed
                        elif any(b < 0x20 or b > 0x7E for b in file_data[:50]) and b'<' not in file_data[:100]:
                            needs_decompression = True
                            print("Binary data detected, attempting decompression")
                    
                    if needs_decompression:
                        try:
                            decompressed = self._decompress_data(file_data, target_file.uncompressed_size)
                            print(f"Successfully decompressed {len(file_data)} -> {len(decompressed)} bytes")
                            return decompressed
                        except Exception as e:
                            print(f"Decompression failed, returning raw data: {e}")
                            return file_data
                    else:
                        print("No decompression needed")
                        return file_data
                else:
                    print("LZ4 not available, returning raw data")
                    return file_data
                    
        except Exception as e:
            print(f"Error extracting file {filename}: {e}")
            return None
    
    def list_files(self) -> List[str]:
        """List all files in the PAK"""
        if not self.files:
            if not self.read_pak_structure():
                return []
        
        return [f.name for f in self.files]


class BG3MetaParser:
    """Parser for BG3 meta.lsx files"""
    
    @staticmethod
    def parse_lsx_content(lsx_content: bytes) -> ModMetadata:
        """Parse LSX content and extract mod metadata"""
        metadata = ModMetadata()
        
        try:
            # Try to decode as UTF-8, fall back to other encodings
            try:
                content_str = lsx_content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    content_str = lsx_content.decode('utf-8-sig')  # UTF-8 with BOM
                except UnicodeDecodeError:
                    try:
                        content_str = lsx_content.decode('utf-16')  # Try UTF-16
                    except UnicodeDecodeError:
                        content_str = lsx_content.decode('latin-1', errors='ignore')
            
            print(f"Successfully decoded LSX content: {len(content_str)} characters")
            print(f"First 200 characters: {content_str[:200]}")
            
            # Parse XML
            root = ET.fromstring(content_str)
            
            # Navigate to ModuleInfo
            module_info = None
            for region in root.findall('.//node[@id="ModuleInfo"]'):
                module_info = region
                break
            
            if module_info is None:
                print("No ModuleInfo region found")
                return metadata
            
            # Find the main module node
            main_node = module_info.find('.//node[@id="Module"]')
            if main_node is None:
                main_node = module_info.find('.//node')
            
            if main_node is None:
                print("No module node found")
                return metadata
            
            # Extract attributes
            for attr in module_info.findall('.//attribute'):
                attr_id = attr.get('id', '')
                attr_value = attr.get('value', '')
                
                if attr_id == 'Name':
                    metadata.name = attr_value
                elif attr_id == 'Description':
                    metadata.description = attr_value
                elif attr_id == 'Author':
                    metadata.author = attr_value
                elif attr_id == 'Version':
                    metadata.version = attr_value
                elif attr_id == 'UUID':
                    metadata.uuid = attr_value
                elif attr_id == 'Folder':
                    metadata.folder = attr_value
            
            # Extract dependencies
            dependencies_node = root.find('.//node[@id="Dependencies"]')
            if dependencies_node is not None:
                for dep_node in dependencies_node.findall('.//node[@id="ModuleShortDesc"]'):
                    dep_info = {}
                    for attr in dep_node.findall('.//attribute'):
                        attr_id = attr.get('id', '')
                        attr_value = attr.get('value', '')
                        
                        if attr_id in ['Name', 'UUID', 'Version']:
                            dep_info[attr_id.lower()] = attr_value
                    
                    if dep_info:
                        metadata.dependencies.append(dep_info)

            # Extract conflicts
            conflicts_node = root.find('.//node[@id="Conflicts"]')
            if conflicts_node is not None:
                for dep_node in conflicts_node.findall('.//node[@id="ModuleShortDesc"]'):
                    dep_info = {}
                    for attr in dep_node.findall('.//attribute'):
                        attr_id = attr.get('id', '')
                        attr_value = attr.get('value', '')
                        
                        if attr_id in ['Name', 'UUID', 'Version']:
                            dep_info[attr_id.lower()] = attr_value
                    
                    if dep_info:
                        metadata.conflicts.append(dep_info)
            
        except Exception as e:
            print(f"Error parsing LSX content: {e}")
            # Show first 100 bytes as hex for debugging
            hex_data = ' '.join(f'{b:02x}' for b in lsx_content[:100])
            print(f"First 100 bytes (hex): {hex_data}")
            import traceback
            traceback.print_exc()
        
        return metadata


def extract_bg3_mod_info(pak_path: str) -> Optional[ModMetadata]:
    """
    Extract mod information from a BG3 PAK file
    
    Args:
        pak_path: Path to the PAK file
        
    Returns:
        ModMetadata object with extracted information, or None if failed
    """
    reader = BG3PakReader(pak_path)
    
    # List all files to find meta.lsx
    files = reader.list_files()
    print(f"Found {len(files)} files in PAK")
    
    # Find meta.lsx file
    found_meta_path = None
    for file_path in files:
        if file_path.lower().endswith('meta.lsx'):
            found_meta_path = file_path
            print(f"Found meta file: {file_path}")
            break
    
    if not found_meta_path:
        print("Available files:")
        for f in files[:10]:  # Show first 10 files
            print(f"  {f}")
        print(f"No meta.lsx found in PAK file: {pak_path}")
        return None
    
    # Extract meta.lsx content
    meta_content = reader.extract_file(found_meta_path)
    if not meta_content:
        print(f"Failed to extract meta.lsx from: {pak_path}")
        return None
    
    print(f"Extracted meta.lsx: {len(meta_content)} bytes")
    
    # Parse the metadata
    parser = BG3MetaParser()
    metadata = parser.parse_lsx_content(meta_content)
    
    return metadata

def export_mods_to_json_objects(mod_list: List[ModMetadata], output_file: str):
    """
    Export mod metadata to JSON file with dependencies/conflicts as JSON objects
    """
    output_data = {}
    
    for mod in mod_list:
        output_data[mod.name] = {
            "description": mod.description,
            "uuid": mod.uuid,
            "Author": mod.author,
            "Version": mod.version,
            "dependencies": mod.dependencies if mod.dependencies else [],
            "conflicts": mod.conflicts if mod.conflicts else []
        }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"Exported {len(mod_list)} mods to {output_file}")

def extract_mod_data(pak_folder, los_data_folder,mod_info_list = []):
    """
    Export mods metadata to JSON file with dependencies/conflicts as JSON objects
    """
    for pak_file in os.listdir(pak_folder):
        if pak_file.endswith(".pak"):
            mod_info = extract_bg3_mod_info(os.path.join(pak_folder, pak_file))
            if mod_info:
                mod_info_list.append(mod_info)
        elif os.path.isdir(os.path.join(pak_folder, pak_file)):
            for sub_pak in os.listdir(os.path.join(pak_folder, pak_file)):
                if sub_pak.endswith(".pak"):
                    mod_info = extract_bg3_mod_info(os.path.join(pak_folder, pak_file, sub_pak))
                    if mod_info:
                        mod_info_list.append(mod_info)

    export_mods_to_json_objects(mod_info_list, os.path.join(los_data_folder, "mods_data.json"))