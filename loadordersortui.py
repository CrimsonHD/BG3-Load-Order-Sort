import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import xml.etree.ElementTree as ET
import json
import os
import shutil
import re
from datetime import datetime
from typing import List
from loadordersort import process_existing_txt_file, process_empty_txt_file
from genmoddata import extract_mod_data

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DRAG_DROP_AVAILABLE = True
except ImportError:
    DRAG_DROP_AVAILABLE = False
    print("tkinterdnd2 not available. Install with: pip install tkinterdnd2")
    TkinterDnD = tk

# Python 3.10.6
# dependency: pip install pyinstaller
# run this code from terminal while in the parent folder to build: python -m PyInstaller --onefile --windowed loadordersortui.py

class Settings:
    def __init__(self):
        self.loadorder_file = ""
        self.pak_folder = ""
        self.groq_api_key = ""
        self.model = "llama-3.3-70b-versatile"
        self.data_directory = ""
        self.settings_file = "settings.json"
        self.load_settings()

    def load_settings(self):
        try:
            with open(self.settings_file, 'r') as f:
                data = json.load(f)
                self.loadorder_file = data.get('loadorder_file', "")
                self.pak_folder = data.get('pak_folder', "")
                self.groq_api_key = data.get('groq_api_key', "")
                self.model = data.get('model', "llama-3.3-70b-versatile")
                self.data_directory = data.get('data_directory', "")
        except FileNotFoundError:
            pass

    def save_settings(self):
        data = {
            'loadorder_file': self.loadorder_file,
            'pak_folder': self.pak_folder,
            'groq_api_key': self.groq_api_key,
            'model': self.model,
            'data_directory': self.data_directory
        }
        with open(self.settings_file, 'w') as f:
            json.dump(data, f)
            
class ModItem:
    def __init__(self, name: str, is_category: bool = False, is_collapsed: bool = False, parent_category: str = None):
        self.name = name
        self.is_category = is_category
        self.is_collapsed = is_collapsed
        self.visible = True  # Whether this item should be shown (based on parent category collapse state)
        self.parent_category = parent_category  # Name of parent category (None for top-level)
        self.level = 0  # Nesting level (0 = top level, 1 = subcategory, etc.)

class ModManagerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Mod Manager - modsettings.lsx Editor")
        self.root.geometry("1000x800")
        
        # Data structures
        self.xml_file_path = ""
        self.state_file = "mod_manager_state.json"
        self.mod_items: List[ModItem] = []  # Single continuous list
        self.collapsed_categories = set()  # Track which categories are collapsed
        
        # GUI setup
        self.settings = Settings()
        self.setup_gui()
        self.load_state()
        
    def setup_gui(self):
       # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Top frame for buttons
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(side=tk.TOP, fill=tk.X)

        # Add settings and load buttons to top right
        settings_button = ttk.Button(top_frame, text="⚙", width=3, command=self.show_settings)
        settings_button.pack(side=tk.RIGHT)
        load_button = ttk.Button(top_frame, text="Load LSX", command=self.load_xml_file)
        load_button.pack(side=tk.RIGHT, padx=(0, 5))

        # Split view for mod list and text editor
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True)

        # Left side - existing tree view
        tree_frame = ttk.Frame(paned_window)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Treeview with custom columns
        columns = ("Index", "Mod Name")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", selectmode="extended")
        
        # Configure columns with fixed widths
        self.tree.heading("#0", text="", anchor=tk.W)
        self.tree.column("#0", width=30, minwidth=30, stretch=False)  # Arrow column - fixed width
        self.tree.heading("Index", text="Index")
        self.tree.column("Index", width=60, minwidth=60, stretch=False)  # Index column - fixed width
        self.tree.heading("Mod Name", text="Mod Name")
        self.tree.column("Mod Name", width=600, minwidth=200, stretch=True)  # Name column - stretches
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Pack treeview and scrollbars
        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        paned_window.add(tree_frame)

        # Right side - text editor
        editor_frame = ttk.Frame(paned_window)
        self.text_editor = tk.Text(editor_frame)
        self.text_editor.pack(fill=tk.BOTH, expand=True)
        self.text_editor.bind('<Alt-Up>', self.move_line_up)
        self.text_editor.bind('<Alt-Down>', self.move_line_down)

        # Add editor scrollbar
        editor_scrollbar = ttk.Scrollbar(editor_frame, orient=tk.VERTICAL, command=self.text_editor.yview)
        editor_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_editor.configure(yscrollcommand=editor_scrollbar.set)
        
        # Load initial content
        self.load_text_editor_content()
        paned_window.add(editor_frame)
        
        # Bind events
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Double-Button-1>", self.on_tree_double_click)
        self.tree.bind("<Key>", self.on_tree_key)
        self.tree.bind("<Motion>", self.on_mouse_motion)
        
        # Drag and drop bindings
        if DRAG_DROP_AVAILABLE:
            self.setup_drag_drop()
        else:
            # Fallback for systems without tkinterdnd2 - bind after the click handler
            self.tree.bind("<ButtonPress-1>", self.on_drag_start, add="+")
            self.tree.bind("<B1-Motion>", self.on_drag_motion)
            self.tree.bind("<ButtonRelease-1>", self.on_drag_end)
        
        # Add context menu
        self.add_context_menu()
        
        # Bottom frame for controls
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X)
        
        ttk.Button(bottom_frame, text="Save Changes", command=self.save_changes).pack(side=tk.RIGHT)
        ttk.Button(bottom_frame, text="Reset", command=self.reset_changes).pack(side=tk.RIGHT, padx=(0, 5))
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def show_settings(self):
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("700x400")

        # File selection for modsettings.lsx
        ttk.Label(settings_window, text="Select modsettings.lsx file:").pack(anchor=tk.W, padx=5)
        file_frame = ttk.Frame(settings_window)
        file_frame.pack(fill=tk.X, padx=5)
        file_entry = ttk.Entry(file_frame)
        file_entry.insert(0, self.settings.loadorder_file)
        file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(file_entry, text="Browse LSX", command=lambda: self.browse_xml_file(file_entry)).pack(side=tk.RIGHT)        

        # Mods folder
        ttk.Label(settings_window, text="Mods Folder:").pack(anchor=tk.W, padx=5)
        mods_frame = ttk.Frame(settings_window)
        mods_frame.pack(fill=tk.X, padx=5)
        mods_entry = ttk.Entry(mods_frame)
        mods_entry.insert(0, self.settings.pak_folder)
        mods_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(mods_frame, text="Browse", 
                   command=lambda: self.browse_folder(mods_entry)).pack(side=tk.RIGHT)

        # GROQ API Key
        ttk.Label(settings_window, text="GROQ API Key:").pack(anchor=tk.W, padx=5)
        key_frame = ttk.Frame(settings_window)
        key_frame.pack(fill=tk.X, padx=5)
        key_var = tk.StringVar(value=self.settings.groq_api_key)
        key_entry = ttk.Entry(key_frame, show="*", textvariable=key_var)
        key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.show_key = tk.BooleanVar()
        ttk.Checkbutton(key_frame, text="Show", variable=self.show_key,
                       command=lambda: key_entry.config(show="" if self.show_key.get() else "*")).pack(side=tk.RIGHT)

        # Model Selection
        ttk.Label(settings_window, text="Model:").pack(anchor=tk.W, padx=5)
        model_entry = ttk.Entry(settings_window)
        model_entry.insert(0, self.settings.model)
        model_entry.pack(fill=tk.X, padx=5)

        # Data Directory
        ttk.Label(settings_window, text="Load Order Sort Data Directory (where to store the mod data and settings for this program):").pack(anchor=tk.W, padx=5)
        data_frame = ttk.Frame(settings_window)
        data_frame.pack(fill=tk.X, padx=5)
        data_entry = ttk.Entry(data_frame)
        data_entry.insert(0, self.settings.data_directory)
        data_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(data_frame, text="Browse", 
                   command=lambda: self.browse_folder(data_entry)).pack(side=tk.RIGHT)

        # Action Buttons
        button_frame = ttk.Frame(settings_window)
        button_frame.pack(fill=tk.X, padx=5, pady=10)
        ttk.Button(button_frame, text="Generate Mod Data", 
                   command=self.generate_mod_data).pack(side=tk.LEFT)
        self.sort_button = ttk.Button(button_frame, 
                                    text=self.get_sort_button_text(),
                                    command=self.process_sort)
        self.sort_button.pack(side=tk.RIGHT)

        # Save/Cancel buttons
        ttk.Button(settings_window, text="Save", 
                   command=lambda: self.save_settings_dialog(settings_window, 
                                                          file_entry.get(),
                                                          mods_entry.get(),
                                                          key_var.get(),
                                                          model_entry.get(),
                                                          data_entry.get())).pack(pady=5)

    def get_sort_button_text(self):
        txt_path = os.path.join(self.settings.data_directory, "loadorder.txt")
        return "Confirm Changes" if os.path.exists(txt_path) and os.path.getsize(txt_path) > 0 else "Generate Sort Recommendation"

    def move_line_up(self, event):
        """Move the current line up"""
        # Get current line and previous line
        current_index = self.text_editor.index("insert linestart")
        if current_index == "1.0":  # Already at top
            return "break"
            
        current_line = self.text_editor.get("insert linestart", "insert lineend")
        previous_line = self.text_editor.get(f"{current_index}-1l linestart", f"{current_index}-1l lineend")
        
        # Swap the lines
        self.text_editor.delete(f"{current_index}-1l linestart", "insert lineend")
        self.text_editor.insert(f"{current_index}-1l linestart", f"{current_line}\n{previous_line}")
        
        # Move cursor to the moved line
        self.text_editor.mark_set("insert", f"{current_index}-1l linestart")
        return "break"

    def move_line_down(self, event):
        """Move the current line down"""
        # Get current line and next line
        current_index = self.text_editor.index("insert linestart")
        next_index = self.text_editor.index(f"{current_index}+1l")
        
        # Check if we're at the last line
        if self.text_editor.index("end-1c") == self.text_editor.index("insert lineend"):
            return "break"
            
        current_line = self.text_editor.get("insert linestart", "insert lineend")
        next_line = self.text_editor.get(f"{current_index}+1l linestart", f"{current_index}+1l lineend")
        
        # Swap the lines
        self.text_editor.delete(f"{current_index} linestart", f"{next_index} lineend")
        self.text_editor.insert(current_index, f"{next_line}\n{current_line}")
        
        # Move cursor to the moved line
        self.text_editor.mark_set("insert", f"{current_index}+1l linestart")
        return "break"

    def generate_mod_data(self):
        try:
            extract_mod_data(self.settings.pak_folder, self.settings.data_directory)
            self.reset_changes()
            messagebox.showinfo("Success", "Mod data generated successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate mod data: {str(e)}")

    def process_sort(self):
        try:
            if self.get_sort_button_text() == "Generate Sort Recommendation":
                # Generate new sort recommendation
                process_empty_txt_file(self.xml_file_path, os.path.join(self.settings.data_directory, "loadorder.txt"), self.settings.groq_api_key, self.settings.model, os.path.join(self.settings.data_directory, "mods_data.json"))
            else:
                # Process existing sort order
                process_existing_txt_file(self.xml_file_path, 
                                       os.path.join(self.settings.data_directory, "loadorder.txt"))
            messagebox.showinfo("Success", "Sort order processed successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to process sort order: {str(e)}")

    def browse_folder(self, entry_widget):
        folder = filedialog.askdirectory()
        if folder:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, folder)

    def save_settings_dialog(self, window, loadorder_file, pak_folder, api_key, model, data_dir):
        self.settings.loadorder_file = loadorder_file
        self.settings.pak_folder = pak_folder
        self.settings.groq_api_key = api_key
        self.settings.model = model
        self.settings.data_directory = data_dir
        self.settings.save_settings()
        # Reload text editor content with new data directory
        self.load_text_editor_content()
        window.destroy()
        
    def browse_xml_file(self, entry_widget):
        file_path = filedialog.askopenfilename(
            title="Select modsettings.lsx file",
            filetypes=[("LSX files", "*.lsx"), ("XML files", "*.xml"), ("All files", "*.*")]
        )
        if file_path:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, file_path)
            self.xml_file_path = file_path
            self.file_label.config(text=os.path.basename(file_path), foreground="black")
            
    def load_xml_file(self):
        if not self.xml_file_path:
            messagebox.showerror("Error", "Please select an XML file first")
            return
            
        try:
            self.parse_xml_file()
            self.recalculate_all_levels()
            self.populate_treeview()
            self.status_var.set(f"Loaded {len([item for item in self.mod_items if not item.is_category])} mods in {len([item for item in self.mod_items if item.is_category])} categories")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load XML file: {str(e)}")
            
    def parse_xml_file(self):
        """Parse the XML file and extract all items in order"""
        tree = ET.parse(self.xml_file_path)
        root = tree.getroot()
        
        mods_node = root.find(".//node[@id='Mods']")
        if mods_node is None:
            raise ValueError("Could not find Mods node in XML")
            
        module_nodes = mods_node.findall("./children/node[@id='ModuleShortDesc']")
        
        self.mod_items = []
        self.xml_nodes = []  # Store the actual XML nodes
        
        current_parent = None
        current_level = 0
        
        for node in module_nodes:
            name_attr = node.find("./attribute[@id='Name']")
            if name_attr is None:
                continue
                
            name = name_attr.get("value")
            
            # Store the original XML node
            self.xml_nodes.append(node)
            
            # Check if this is a category separator
            if name.startswith("--"):
                category_name = re.sub(r'[-|>]', '', name).strip()
                
                # Determine nesting level based on the number of leading dashes
                sub_category = "-->" in name
                new_level = 1 if sub_category else 0

                # Update parent category based on level
                if new_level == 0:
                    current_parent = None
                elif new_level > current_level:
                    # Find the most recent category at the parent level
                    for i in range(len(self.mod_items) - 1, -1, -1):
                        if self.mod_items[i].is_category and self.mod_items[i].level == new_level - 1:
                            current_parent = self.mod_items[i].name
                            break
                else:
                    # Moving to same or higher level, find appropriate parent
                    if new_level == 0:
                        current_parent = None
                    else:
                        for i in range(len(self.mod_items) - 1, -1, -1):
                            if self.mod_items[i].is_category and self.mod_items[i].level == new_level - 1:
                                current_parent = self.mod_items[i].name
                                break
                
                current_level = new_level
                
                is_collapsed = category_name in self.collapsed_categories
                mod_item = ModItem(category_name, is_category=True, is_collapsed=is_collapsed, parent_category=current_parent)
                mod_item.level = new_level
                self.mod_items.append(mod_item)
            else:
                # This is a mod
                mod_item = ModItem(name, is_category=False, parent_category=current_parent)
                mod_item.level = current_level + 1 if current_parent else 0
                self.mod_items.append(mod_item)
                
        # Update visibility based on collapsed state
        self.update_visibility()
                
    def update_visibility(self):
        """Update visibility of items based on collapsed categories (flat structure)"""
        # Track which categories are collapsed by walking through the list
        collapsed_ancestors = set()
        current_category_stack = []  # Stack to track nested categories
        
        for item in self.mod_items:
            if item.is_category:
                # Update the category stack based on this category's level
                # Remove categories from stack that are at same or higher level
                current_category_stack = [(cat, level) for cat, level in current_category_stack if level < item.level]
                
                # Add this category to the stack
                current_category_stack.append((item.name, item.level))
                
                # Check if this category should be visible
                # Look at all ancestor categories (excluding current one)
                ancestor_categories = [cat for cat, level in current_category_stack[:-1]]
                item.visible = not any(cat in collapsed_ancestors for cat in ancestor_categories)
                
                # If this category is collapsed, add it to collapsed ancestors
                if item.is_collapsed:
                    collapsed_ancestors.add(item.name)
                else:
                    # Remove from collapsed ancestors if it was there
                    collapsed_ancestors.discard(item.name)
            else:
                # This is a mod - check if any ancestor category is collapsed
                ancestor_categories = [cat for cat, level in current_category_stack]
                item.visible = not any(cat in collapsed_ancestors for cat in ancestor_categories)
                
    def populate_treeview(self):
        """Populate the treeview with all visible items in flat structure (subcategories are visual only)"""
        # Store current column widths before clearing
        col0_width = self.tree.column("#0")['width']
        index_width = self.tree.column("Index")['width'] 
        name_width = self.tree.column("Mod Name")['width']
        
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Immediately restore column widths after clearing
        self.tree.column("#0", width=col0_width, minwidth=30, stretch=False)
        self.tree.column("Index", width=index_width, minwidth=60, stretch=False)
        self.tree.column("Mod Name", width=name_width, minwidth=200, stretch=True)
        
        # Store original indices as item data
        self.item_to_original_index = {}
        
        visible_index = 1
        
        for i, item in enumerate(self.mod_items):
            if not item.visible:
                continue
                
            if item.is_category:
                # Category item with collapse arrow
                arrow = "▼" if not item.is_collapsed else "▶"
                indent = "        " * item.level  # Use 8 spaces per level for better visibility
                item_id = self.tree.insert("", "end", 
                                         text=arrow,
                                         values=(visible_index, f"{indent}-- {item.name} --"),
                                         tags=("category",))
                # Store the original index for reference
                self.item_to_original_index[item_id] = i
                visible_index += 1
            else:
                # Regular mod item - indent based on its level
                indent = "        " * item.level  # Use 8 spaces per level for better visibility
                item_id = self.tree.insert("", "end", 
                                         text="",
                                         values=(visible_index, f"{indent}{item.name}"),
                                         tags=("mod",))
                self.item_to_original_index[item_id] = i
                visible_index += 1
                
        # Configure tags
        self.tree.tag_configure("category", background="#e8e8e8", font=("TkDefaultFont", 9, "bold"))
        self.tree.tag_configure("mod", background="white")
        
        # Force update the display to ensure layout is stable
        self.tree.update_idletasks()

        
    def on_tree_click(self, event):
        """Handle tree clicks, especially for collapse/expand"""
        region = self.tree.identify_region(event.x, event.y)
        item = self.tree.identify_row(event.y)
        
        # Check if this is a category click for folding
        if item and "category" in self.tree.item(item, "tags"):
            # Only toggle if clicked on the tree icon area or text, not for drag start
            # Also check if this is NOT a Ctrl+click or Shift+click (which should be for selection)
            if (region == "tree" or (region == "cell" and event.x < 100)) and not (event.state & 0x4) and not (event.state & 0x1):
                # Toggle collapse state
                original_index = self.item_to_original_index[item]
                category_item = self.mod_items[original_index]
                category_item.is_collapsed = not category_item.is_collapsed
                
                # Update collapsed categories set
                if category_item.is_collapsed:
                    self.collapsed_categories.add(category_item.name)
                else:
                    self.collapsed_categories.discard(category_item.name)
                    
                # Update visibility and repopulate
                self.update_visibility()
                self.populate_treeview()
                return "break"  # Prevent other event handlers from running
                
    def on_tree_double_click(self, event):
        """Handle double-click events"""
        pass
        
    def on_tree_key(self, event):
        """Handle keyboard events"""
        if event.keysym == "Return":
            self.set_item_index()
            
    def setup_drag_drop(self):
        """Setup drag and drop functionality using tkinterdnd2"""
        # Make the treeview a drop target
        self.tree.drop_target_register(DND_FILES)
        
        # Bind drag and drop events - use add="+" to not override click handler
        self.tree.bind("<ButtonPress-1>", self.on_drag_start, add="+")
        self.tree.bind("<B1-Motion>", self.on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_drag_end)
        
    def on_drag_start(self, event):
        """Handle start of potential drag operation (just store info, don't start dragging yet)"""
        # Get the item under the cursor
        item = self.tree.identify_row(event.y)
        if not item:
            return
            
        # Don't start drag for category folding clicks
        if item and "category" in self.tree.item(item, "tags"):
            region = self.tree.identify_region(event.x, event.y)
            # Check if this is a folding click (not Ctrl or Shift click)
            if (region == "tree" or (region == "cell" and event.x < 100)) and not (event.state & 0x4) and not (event.state & 0x1):
                return  # Let the folding click handler take care of this
            
        # Store potential drag start information (but don't start dragging yet)
        self.drag_start_item = item
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.drag_active = False  # Flag to track if we're actually dragging
        
    def on_drag_motion(self, event):
        """Handle drag motion - only start dragging after significant movement"""
        if not hasattr(self, 'drag_start_item') or not self.drag_start_item:
            return
            
        # Calculate distance moved
        dx = abs(event.x - self.drag_start_x)
        dy = abs(event.y - self.drag_start_y)
        
        # Only start dragging if moved more than 5 pixels
        if not self.drag_active and (dx > 5 or dy > 5):
            self.drag_active = True
            self.drag_items = list(self.tree.selection())
            self.tree.config(cursor="hand2")
            
        if self.drag_active:
            # Get the item under the cursor
            target_item = self.tree.identify_row(event.y)
            if target_item and target_item not in self.drag_items:
                # Highlight the drop target
                self.tree.selection_set(self.drag_items + [target_item])
            else:
                # Only show dragged items
                self.tree.selection_set(self.drag_items)
                
    def on_drag_end(self, event):
        """Handle end of drag operation"""
        if not hasattr(self, 'drag_start_item') or not self.drag_start_item:
            return
            
        # Reset cursor
        self.tree.config(cursor="")
        
        # Only perform move if we were actually dragging
        if hasattr(self, 'drag_active') and self.drag_active:
            # Get the drop target
            target_item = self.tree.identify_row(event.y)
            
            if target_item and hasattr(self, 'drag_items') and target_item not in self.drag_items:
                # Perform the move operation
                self.move_items_to_target(target_item)
        
        # Clean up drag state
        self.drag_start_item = None
        self.drag_active = False
        if hasattr(self, 'drag_items'):
            delattr(self, 'drag_items')
        
    def move_items_to_target(self, target_item):
        """Move dragged items to the target position"""
        # Get target index
        target_index = None
        for i, item_id in enumerate(self.tree.get_children()):
            if item_id == target_item:
                target_index = self.item_to_original_index[item_id]
                break
                
        if target_index is None:
            return
            
        # Get selected items
        selected_items = self.get_selected_mod_items()
        if not selected_items:
            return
            
        # Get the items and XML nodes to move
        items_to_move = [item for _, item in selected_items]
        xml_nodes_to_move = [self.xml_nodes[i] for i, _ in selected_items]
        
        # Remove items from their current positions (in reverse order)
        for i, _ in reversed(selected_items):
            if i < target_index:
                target_index -= 1
            self.mod_items.pop(i)
            self.xml_nodes.pop(i)
            
        # Insert items at the target position
        for i, (item, xml_node) in enumerate(zip(items_to_move, xml_nodes_to_move)):
            self.mod_items.insert(target_index + i, item)
            self.xml_nodes.insert(target_index + i, xml_node)
            
        # Update levels for all items after the move
        self.recalculate_all_levels()
        
        # Update display
        self.update_visibility()
        self.populate_treeview()
        
    def on_mouse_motion(self, event):
        """Handle mouse motion for hover effects"""
        # This could be used to show/hide collapse arrows on hover
        pass
        
    def add_context_menu(self):
        """Add right-click context menu"""
        def show_context_menu(event):
            try:
                selection = self.tree.selection()
                if selection:
                    # Clear previous menu
                    context_menu.delete(0, tk.END)
                    
                    # Get selected items info
                    selected_items = self.get_selected_mod_items()
                    selected_categories = [item for _, item in selected_items if item.is_category]
                    
                    # Always show basic move and index options
                    context_menu.add_command(label="Move Up", command=self.move_items_up)
                    context_menu.add_command(label="Move Down", command=self.move_items_down)
                    context_menu.add_separator()
                    context_menu.add_command(label="Set Index...", command=self.set_item_index)
                    
                    # Add subcategory option if categories are selected
                    if selected_categories:
                        context_menu.add_separator()
                        if len(selected_categories) == 1:
                            # Single category selected
                            context_menu.add_command(label="Make Subcategory of Above Category", 
                                                   command=self.make_subcategory_of_above)
                        elif len(selected_categories) > 1:
                            # Multiple categories selected
                            context_menu.add_command(label="Make Sub Categories of Above Category", 
                                                   command=self.make_subcategory_of_above)
                    
                    context_menu.post(event.x_root, event.y_root)
            except:
                pass
                
        context_menu = tk.Menu(self.tree, tearoff=0)
        self.tree.bind("<Button-3>", show_context_menu)
        
    def make_subcategory_of_above(self):
        """Make selected categories subcategories of the category above them (visual only)"""
        selected_items = self.get_selected_mod_items()
        selected_categories = [(i, item) for i, item in selected_items if item.is_category]
        
        if not selected_categories:
            return
            
        # Find the target parent category (the category above the first selected category)
        first_category_index = selected_categories[0][0]
        target_parent = None
        target_parent_level = -1
        
        # Look backwards from the first selected category to find a category
        for i in range(first_category_index - 1, -1, -1):
            if self.mod_items[i].is_category:
                target_parent = self.mod_items[i].name
                target_parent_level = self.mod_items[i].level
                break
                
        if not target_parent:
            messagebox.showwarning("Warning", "No category found above the selected categories.")
            return
            
        # Confirm the action
        category_names = [item.name for _, item in selected_categories]
        if len(category_names) == 1:
            message = f"Make '{category_names[0]}' a subcategory of '{target_parent}'?"
        else:
            message = f"Make {len(category_names)} categories subcategories of '{target_parent}'?"
            
        if not messagebox.askyesno("Confirm Subcategory", message):
            return
            
        # Update the parent category and level for selected categories and their contents
        for i, category_item in selected_categories:
            # Set new parent and level (visual only - don't move items in the list)
            category_item.parent_category = target_parent
            category_item.level = target_parent_level + 1
            
            # Update all items that come after this category until the next category of same or higher level
            self.update_items_under_category_visual(i, category_item.level)
            
        # Update visibility and refresh display
        self.update_visibility()
        self.populate_treeview()
        
    def update_items_under_category_visual(self, category_index, category_level):
        """Update visual level of items under a category (don't change XML structure)"""
        # Look at items after this category until we hit another category at same or higher level
        for i in range(category_index + 1, len(self.mod_items)):
            item = self.mod_items[i]
            
            if item.is_category:
                # If we hit a category at same or higher level, stop
                if item.level <= category_level:
                    break
                # Otherwise, this is a subcategory - update its level
                item.level = category_level + (item.level - category_level) + 1
            else:
                # This is a mod under the category
                item.level = category_level + 1
                item.parent_category = self.mod_items[category_index].name
        
    def get_category_level(self, category_name):
        """Get the nesting level of a category"""
        for item in self.mod_items:
            if item.is_category and item.name == category_name:
                return item.level
        return 0
        
    def get_selected_mod_items(self):
        """Get selected items (both mods and categories) with their indices"""
        selection = self.tree.selection()
        selected_items = []
        
        for item in selection:
            original_index = self.item_to_original_index[item]
            selected_items.append((original_index, self.mod_items[original_index]))
                
        return sorted(selected_items, key=lambda x: x[0])  # Sort by original index
        
    def move_items_up(self):
        """Move selected mod items up"""
        selected_items = self.get_selected_mod_items()
        if not selected_items:
            return
            
        # Check if we can move up
        first_index = selected_items[0][0]
        if first_index <= 0:
            return
            
        # Find the previous item
        target_index = first_index - 1
            
        # Move items in both data structures
        items_to_move = [item for _, item in selected_items]
        xml_nodes_to_move = [self.xml_nodes[i] for i, _ in selected_items]
        
        # Remove items from their current positions (in reverse order)
        for i, _ in reversed(selected_items):
            self.mod_items.pop(i)
            self.xml_nodes.pop(i)
            
        # Insert at new position
        for i, (item, xml_node) in enumerate(zip(items_to_move, xml_nodes_to_move)):
            self.mod_items.insert(target_index + i, item)
            self.xml_nodes.insert(target_index + i, xml_node)
            
        # Update levels for all items after the move
        self.recalculate_all_levels()
        
        self.update_visibility()
        self.populate_treeview()
        
    def move_items_down(self):
        """Move selected mod items down"""
        selected_items = self.get_selected_mod_items()
        if not selected_items:
            return
            
        # Check if we can move down
        last_index = selected_items[-1][0]
        if last_index >= len(self.mod_items) - 1:
            return
            
        # Move to after the next item
        target_index = last_index + 2 - len(selected_items)
            
        # Move items in both data structures
        items_to_move = [item for _, item in selected_items]
        xml_nodes_to_move = [self.xml_nodes[i] for i, _ in selected_items]
        
        # Remove items from their current positions (in reverse order)
        for i, _ in reversed(selected_items):
            self.mod_items.pop(i)
            self.xml_nodes.pop(i)
            
        # Insert at new position
        for i, (item, xml_node) in enumerate(zip(items_to_move, xml_nodes_to_move)):
            self.mod_items.insert(target_index + i, item)
            self.xml_nodes.insert(target_index + i, xml_node)
            
        # Update levels for all items after the move
        self.recalculate_all_levels()
        
        self.update_visibility()
        self.populate_treeview()
        
    def set_item_index(self):
        """Set specific index for selected items (multi-select supported)"""
        selected_items = self.get_selected_mod_items()
        if not selected_items:
            messagebox.showwarning("Warning", "Please select at least one item")
            return
            
        # Count total items (including categories) for max index
        total_items = len(self.mod_items)
        
        new_idx = simpledialog.askinteger(
            "Set Index", 
            f"Enter starting index for {len(selected_items)} selected item(s) (1-{total_items}):",
            initialvalue=1,
            minvalue=1,
            maxvalue=total_items
        )
        
        if new_idx is None:
            return
            
        new_idx -= 1  # Convert to 0-based
        
        # Get the items and XML nodes to move
        items_to_move = [item for _, item in selected_items]
        xml_nodes_to_move = [self.xml_nodes[i] for i, _ in selected_items]
        
        # Remove items from their current positions (in reverse order to maintain indices)
        for i, _ in reversed(selected_items):
            self.mod_items.pop(i)
            self.xml_nodes.pop(i)
            
        # Insert items at the new position
        for i, (item, xml_node) in enumerate(zip(items_to_move, xml_nodes_to_move)):
            self.mod_items.insert(new_idx + i, item)
            self.xml_nodes.insert(new_idx + i, xml_node)
            
        # Update levels for all items after the move
        self.recalculate_all_levels()
        
        self.update_visibility()
        self.populate_treeview()
        
        # Select the moved items
        self.select_items_by_name([item.name for item in items_to_move])
        
    def recalculate_all_levels(self):
        """Recalculate levels and parent categories for all items based on their current positions"""
        current_category_stack = []  # Stack of (category_name, level) tuples
        
        for item in self.mod_items:
            if item.is_category:
                # Update the category stack based on this category's level
                # Remove categories from stack that are at same or higher level
                current_category_stack = [(cat, level) for cat, level in current_category_stack if level < item.level]
                
                # Determine parent category
                if current_category_stack:
                    item.parent_category = current_category_stack[-1][0]
                else:
                    item.parent_category = None
                    
                # Add this category to the stack
                current_category_stack.append((item.name, item.level))
            else:
                # This is a mod - set its level and parent based on current category stack
                if current_category_stack:
                    # Under a category
                    item.level = current_category_stack[-1][1] + 1
                    item.parent_category = current_category_stack[-1][0]
                else:
                    # Top level mod
                    item.level = 0
                    item.parent_category = None
        
    def select_items_by_name(self, names):
        """Select items in the tree by their names"""
        self.tree.selection_remove(self.tree.selection())
        
        for item_id in self.tree.get_children():
            item_name = self.tree.item(item_id, "values")[1].strip()
            # Remove category formatting for comparison
            clean_name = re.sub(r'^(\s*--\s*|\s*--\s*$)', '', item_name).strip()
            if clean_name in names or item_name in names:
                self.tree.selection_add(item_id)

    def load_text_editor_content(self):
        """Load content from loadorder.txt into the text editor"""
        self.text_editor.delete(1.0, tk.END)
        if self.settings.data_directory:
            txt_path = os.path.join(self.settings.data_directory, "loadorder.txt")
            try:
                if os.path.exists(txt_path):
                    with open(txt_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    self.text_editor.insert(1.0, content)
                else:
                    self.text_editor.insert(1.0, "# Create or load a loadorder.txt file\n# Use Alt+Up/Down to move lines")
            except Exception as e:
                self.text_editor.insert(1.0, f"Error loading loadorder.txt: {str(e)}")

    def save_text_editor_content(self):
        """Save text editor content to loadorder.txt"""
        if self.settings.data_directory:
            txt_path = os.path.join(self.settings.data_directory, "loadorder.txt")
            try:
                content = self.text_editor.get(1.0, tk.END).strip()
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.status_var.set("Saved loadorder.txt")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save loadorder.txt: {str(e)}")

    def save_changes(self):
        """Save changes back to the XML file"""
        if not self.xml_file_path:
            messagebox.showerror("Error", "No XML file loaded")
            return
            
        try:
            self.update_xml_file()
            self.save_text_editor_content()
            self.save_state()
            messagebox.showinfo("Success", "Changes saved successfully")
            self.status_var.set("Changes saved")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save changes: {str(e)}")
            
    def update_xml_file(self):
        """Update the XML file with current mod organization by moving existing nodes"""
        # Create backup
        backup_file = f"{self.xml_file_path}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        shutil.copy2(self.xml_file_path, backup_file)
        
        # Parse XML
        tree = ET.parse(self.xml_file_path)
        root = tree.getroot()
        mods_node = root.find(".//node[@id='Mods']")
        children = mods_node.find("./children")
        
        # Remove all existing mod nodes from their current positions
        for node in children.findall("./node[@id='ModuleShortDesc']"):
            children.remove(node)
            
        # Re-insert the nodes in the new order (keep original XML structure - no subcategory indicators)
        for i, item in enumerate(self.mod_items):
            # Use the corresponding XML node from our stored list without modification
            children.append(self.xml_nodes[i])
                    
        # Write back to file with original formatting preserved
        tree.write(self.xml_file_path, encoding="UTF-8", xml_declaration=True)
        
    def indent_xml(self, elem, level=0):
        """Add proper indentation to XML elements"""
        indent = "\n" + "    " * level
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "    "
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
            for elem in elem:
                self.indent_xml(elem, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = indent
        
    def reset_changes(self):
        """Reset to original XML state"""
        if messagebox.askyesno("Confirm Reset", "Reset all changes? This will reload from the LSX file."):
            self.load_xml_file()
            self.load_text_editor_content()
            
    def save_state(self):
        """Save current state to file"""
        state = {
            "xml_file_path": self.xml_file_path,
            "collapsed_categories": list(self.collapsed_categories),
            "window_geometry": self.root.geometry()
        }
        
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"Failed to save state: {e}")
            
    def load_state(self):
        """Load state from file"""
        if not os.path.exists(self.state_file):
            return
            
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                
            self.xml_file_path = state.get("xml_file_path", "")
            self.collapsed_categories = set(state.get("collapsed_categories", []))
            
            if self.xml_file_path:
                self.file_label.config(text=os.path.basename(self.xml_file_path), foreground="black")
                
            # Restore window geometry
            geometry = state.get("window_geometry")
            if geometry:
                self.root.geometry(geometry)
                
        except Exception as e:
            print(f"Failed to load state: {e}")
            
    def on_closing(self):
        """Handle application closing"""
        self.save_state()
        self.root.destroy()

def main():
    if DRAG_DROP_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        
    app = ModManagerGUI(root)
    
    # Handle window closing
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    root.mainloop()

if __name__ == "__main__":
    main()