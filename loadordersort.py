import xml.etree.ElementTree as ET
import json
import os
import shutil
import requests
import re
import sys
from datetime import datetime
from pydantic import ValidationError, Field, create_model
import random
from typing import Dict, List

def process_empty_txt_file(xml_file_path, txt_file_path, api_key = GROQ_API_KEY, model = "llama-3.3-70b-versatile", mods_data_path = None):
    """Create a JSON sorting of unsorted mods into categories via llm with random mod descriptions per category as context"""
    print("Processing XML to identify categories and unsorted nodes...")

    # Load mod descriptions if available
    mods_data = {}
    if mods_data_path and os.path.exists(mods_data_path):
        mods_data = load_mods_data(mods_data_path)
        print(f"Loaded descriptions for {len(mods_data)} mods")
    
    # Parse the XML file
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    
    # Find all ModuleShortDesc nodes
    module_nodes = root.findall(".//node[@id='ModuleShortDesc']")
    
    cleaned_category_separators = []
    unsorted_nodes = []
    existing_categorized_nodes = {}
    current_category = None
    found_unsorted = False
    
    # Identify category separators, sorted nodes, and unsorted nodes
    for node in module_nodes:
        name_attr = node.find("./attribute[@id='Name']")
        if name_attr is not None:
            name = name_attr.get("value")
            
            # Check if this is a category separator (starts with dashes)
            if name.startswith("--"):
                
                # Check if this is the UNSORTED category
                if "UNSORTED" in name:
                    found_unsorted = True
                    continue
                
                # Clean the category name for better readability and tracking existing mods, exclude unsorted separator
                clean_category = re.sub(r'[-|>]', '', name).strip()
                current_category = clean_category
                existing_categorized_nodes[clean_category] = []

                cleaned_category_separators.append(clean_category)

                # If we were in the unsorted section, now we're done with it
                if found_unsorted:
                    found_unsorted = False
            
            # If we're in the unsorted section, add this node to unsorted_nodes
            elif found_unsorted:
                unsorted_nodes.append(name)
            # If we're in a regular category, add this mod to existing categorized mods
            else:
                if current_category:
                    existing_categorized_nodes[current_category].append(name)
    
    if not unsorted_nodes:
        print("No unsorted nodes found.")
        return
    
    # Prepare data for Groq

    # Create enhanced mod information with descriptions if available
    unsorted_mods = []
    existing_categorized_mods = {}
    if mods_data:
        for mod_name in unsorted_nodes:
            mod_info = {"name": mod_name}
            if mod_name in mods_data and "description" in mods_data[mod_name]:
                mod_info["description"] = mods_data[mod_name]["description"]
            unsorted_mods.append(mod_info)

        # Prepare existing categorized mods with descriptions
        for category, mod_names in existing_categorized_nodes.items():
            if mod_names:  # Only include categories that have mods
                existing_categorized_mods[category] = []
                for mod_name in mod_names:
                    mod_info = {"name": mod_name}
                    if mod_name in mods_data and "description" in mods_data[mod_name]:
                        mod_info["description"] = mods_data[mod_name]["description"]
                    existing_categorized_mods[category].append(mod_info)
    else:
        unsorted_mods = unsorted_nodes
        existing_categorized_mods = existing_categorized_nodes

    groq_query = {
        "task": "Categorize these mod names into the most appropriate categories.",
        "categories": cleaned_category_separators,
        "mods_to_categorize": unsorted_mods,
        "existing_categorized_mods": existing_categorized_mods
    }
    
    # Call Groq API and get categorization
    print(f"Found {len(unsorted_nodes)} mods to categorize into {len(cleaned_category_separators)} categories")
    categorization = ask_groq(groq_query, model, mods_data)

    # remove duplicate values from categorization, CategorizationModel validates in a similar fashion
    for category, mods in categorization.items():
        categorization[category] = list(set(mods))
    
    # Create a mapping of mod -> category (swap keys with values) to ensure each mod only appears once
    mod_to_category = {}
    for category, mods in categorization.items():
        for mod in mods:
            mod_to_category[mod] = category
    
    # Rebuild the categorization with normalized data
    categorized_mods = set(mod_to_category.keys())
    normalized_categorization = {category: [] for category in cleaned_category_separators}
    for mod, category in mod_to_category.items():
        if category in normalized_categorization:
            # CategorizationModel output should be the same as this
            normalized_categorization[category].append(mod)
        else:
            categorized_mods -= {mod}
    
    # Check if all unsorted mods were categorized
    all_mods = set(unsorted_nodes)
    uncategorized_mods = all_mods - categorized_mods

    if uncategorized_mods:
        print(f"Warning: {len(uncategorized_mods)} mods were not categorized!")
        print(f"Uncategorized mods: {list(uncategorized_mods)}")
        normalized_categorization['UNSORTED'] = list(uncategorized_mods)

    # Write the categorization to the TXT file
    with open(txt_file_path, 'w') as f:
        f.write(format_json_with_trailing_commas(normalized_categorization))
    print(f"Categorization saved to {txt_file_path}")
    
    # Print a summary of the categorization
    print("\nCategorization Summary:")
    for category, mods in normalized_categorization.items():
        if mods:
            print(f"{category}: {len(mods)} mods")
    
def process_existing_txt_file(xml_file_path, txt_file_path):
    """Move the mods into the correct categories in the lsx based on json"""
    print("Reorganizing modsettings.lsx based on categorization from loadorder.txt file...")
    
    # Load categorization from TXT file
    with open(txt_file_path, 'r') as f:
        categorization = json.loads(clean_json_for_parsing(f.read()))
    
    # Parse the XML file
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    
    # Get the Mods node where all ModuleShortDesc nodes are located
    mods_node = root.find(".//node[@id='Mods']")
    
    if mods_node is None:
        print("Error: Could not find Mods node in XML")
        return
    
    # Create a backup of the XML file before making changes
    backup_file = f"{xml_file_path}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    # tree.write(backup_file, encoding="UTF-8", xml_declaration=True)
    shutil.copy2(xml_file_path, backup_file)

    print(f"Created backup of modsettings file at {backup_file}")
    
    # Get all ModuleShortDesc nodes
    module_nodes = mods_node.findall("./children/node[@id='ModuleShortDesc']")
    
    # Create a mapping of category names to their XML representation
    category_mapping = {}
    
    # First, identify all category nodes
    category_nodes = []
    for node in module_nodes:
        name_attr = node.find("./attribute[@id='Name']")
        if name_attr is not None and name_attr.get("value").startswith("--"):
            category_name = name_attr.get("value")
            cleaned_name = re.sub(r'[-|>]', '', category_name).strip()
            category_mapping[cleaned_name] = category_name
            category_nodes.append((category_name, node))
    
    # Find all nodes in the UNSORTED category that need to be moved
    unsorted_category = None
    for cat_name, _ in category_nodes:
        if "UNSORTED" in cat_name:
            unsorted_category = cat_name
            break
    
    if not unsorted_category:
        print("No UNSORTED category found in the XML.")
        return
    
    # Build a list of mod names that need to be moved
    nodes_to_move = []
    in_unsorted = False
    unsorted_node_objs = []
    
    # Find all nodes between UNSORTED and the next category
    for node in module_nodes:
        name_attr = node.find("./attribute[@id='Name']")
        if name_attr is None:
            continue
            
        name = name_attr.get("value")
        
        # Check if we're entering the UNSORTED category
        if name == unsorted_category:
            in_unsorted = True
            continue
            
        # Check if we're leaving the UNSORTED category (found another category)
        if in_unsorted and name.startswith("--"):
            in_unsorted = False
            break
            
        # Collect nodes within the UNSORTED category
        if in_unsorted and not name.startswith("--"):
            unsorted_node_objs.append((name, node))
    
    # Create a mapping of mod names to target categories
    mod_to_category = {}
    for category, mods in categorization.items():
        for mod in mods:
            if category != "UNSORTED":  # Skip mods that should stay in UNSORTED
                mod_to_category[mod] = category
    
    # Create a plan for moving nodes and match the order of categories in mod_to_category (this doesn't modify the XML yet)
    move_plan = []
    for mod_name, category in zip(mod_to_category.keys(), mod_to_category.values()):
        for unsorted_mod_name, node in unsorted_node_objs:
            if mod_name == unsorted_mod_name:
                move_plan.append((mod_name, node, mod_to_category[mod_name]))
    
    # Report what's being moved
    print(f"\nMoving {len(move_plan)} nodes:")
    category_counts = {}
    for _, _, category in move_plan:
        category_counts[category] = category_counts.get(category, 0) + 1
    
    for category, count in category_counts.items():
        print(f"  - {count} nodes to '{category}'")
    
    # First, remove all nodes that need to be moved
    for _, node, _ in move_plan:
        mods_node.find("./children").remove(node)
    
    # Now, insert nodes at their new positions
    for mod_name, node, target_category in move_plan:
        # Find all categories in the XML
        for i, check_node in enumerate(module_nodes):
            name_attr = check_node.find("./attribute[@id='Name']")
            if name_attr is None:
                continue
                
            name = name_attr.get("value")
            
            # Find the category node for our target category
            if name.startswith("--"):
                cleaned_name = re.sub(r'[-|>]', '', name).strip()
                
                # If this is our target category, insert after this node
                if cleaned_name == target_category:
                    # Look for the next category separator or end of list
                    insertion_index = len(module_nodes)  # Default to end of list
                    
                    for j in range(i + 1, len(module_nodes)):
                        next_node = module_nodes[j]
                        next_name_attr = next_node.find("./attribute[@id='Name']")
                        if next_name_attr is not None:
                            next_name = next_name_attr.get("value")
                            # If we found another category separator, insert before it
                            if next_name.startswith("--"):
                                insertion_index = j
                                break
                    
                    # Insert at the calculated position
                    children = mods_node.find("./children")
                    children.insert(insertion_index, node)
                    
                    # Update module_nodes to reflect this insertion
                    module_nodes = children.findall("./node[@id='ModuleShortDesc']")
                    break
    
    # Write the modified XML back to the file
    tree.write(xml_file_path, encoding="UTF-8", xml_declaration=True)
    # Clear the text file after successful XML update
    with open(txt_file_path, 'w') as f:
        f.write('')
    print(f"\nXML file has been reorganized and saved to {xml_file_path}")
    print("To undo this change, use the backup file created at the beginning of this operation.")

def load_mods_data(mods_data_path):
    """Load mod descriptions from JSON file"""
    try:
        with open(mods_data_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: mods_data.json not found at {mods_data_path}")
        return {}
    except json.JSONDecodeError as e:
        print(f"Warning: Error parsing mods_data.json: {e}")
        return {}

def ask_groq(query, model = "llama-3.3-70b-versatile", mods_data={}, max_retries=3):
    """
    Send a query to the Groq API and return the categorization.
    
    Args:
        query (dict): The query containing category information and mods to categorize
        
    Returns:
        dict: Categorized mods
    """
    # Extract mod names for validation (handle both old and new format)
    if mods_data:
        mod_names = [mod_info["name"] for mod_info in query["mods_to_categorize"]]
    else:
        mod_names = query["mods_to_categorize"]

    best_rate = 0
    best_result = None
    for attempt in range(max_retries):
        print(f"Groq API attempt {attempt + 1}/{max_retries}...")
        
        result = _call_groq_api(query, model, mods_data)
        
        if result is not None:
            # Validate the result with Pydantic
            try:
                validated_result = validate_with_pydantic(result, query["categories"], mod_names)
                
                # Check if the result is "good enough" (most mods categorized correctly)
                total_mods = len(mod_names)
                categorized_count = sum(len(mods) for mods in validated_result.values())
                success_rate = categorized_count / total_mods if total_mods > 0 else 0
                
                if success_rate >= 0.95:  # 95% success rate threshold
                    print(f"Categorization successful with {success_rate:.1%} accuracy (% of mods categorized)")
                    return validated_result
                else:
                    print(f"Low accuracy ({success_rate:.1%}), retrying...")
                    if success_rate > best_rate:
                        best_rate = success_rate
                        best_result = validated_result
                    
            except Exception as e:
                print(f"Error validating result: {e}")
                if attempt < max_retries - 1:
                    print("Retrying...")
    
    if best_rate >= 0.5:
        print(f"Using best result with {best_rate:.1%} accuracy (% of mods categorized)")
        return best_result
    else:
        print("All attempts failed, using fallback categorization")
        return create_fallback_categorization(query, mod_names)

def _call_groq_api(query, model= "llama-3.3-70b-versatile", mods_data=None):
    """Internal function to make a single API call to Groq"""
    # Groq API endpoint
    url = "https://api.groq.com/openai/v1/chat/completions"


    # Create a JSON schema to enforce the response format
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False
    }
    json_format = {}
    
    # Add each category as a valid property
    for category in query["categories"]:
        schema["properties"][category] = {
            "type": "array",
            "items": {"type": "string"}
        }
        json_format[category] = ["categorized mods"]    

    # Format the prompt for Groq
    system_prompt = """You are a helpful assistant that categorizes video game mods into appropriate categories.
        Your task is to analyze each mod name (and description where available) and determine which of the pre determined categories it best belongs to.

        You MUST return your answer as a JSON object where:
        1. Keys are ONLY the category names provided by the user (no other keys are allowed)
        2. Values are arrays of mod names from the list provided by the user
        
        CRITICAL: Each mod should be placed in exactly one category.Your response will be parsed programmatically. Any deviation from the exact format will cause errors.

        Respond only with JSON using this format: 
        {json_format}
        """
    
    json_categories = re.sub(r'[\n]', '', json.dumps(query["categories"], indent=1)).strip()
    json_mods = re.sub(r'[\n]', '', json.dumps(query['mods_to_categorize'], indent=1)).strip()

    mods_per_category_limit = 4
    existing_categorized_mods = {
        category: random.sample(query["existing_categorized_mods"][category], min(mods_per_category_limit, len(query["existing_categorized_mods"][category])))
        for category in list(query["existing_categorized_mods"].keys())
    }
    json_categorized_mods = re.sub(r'[\n]', '', json.dumps(existing_categorized_mods, indent=1)).strip()

    user_prompt = f"""I have the following categories of video game mods:
        {json_categories}

        And some of the mods that have already been categorized into the categories:
        {json_categorized_mods}

        And I need to categorize these NEW mods:
        {json_mods}

        Please categorize each mod into the most appropriate, closest matching, existing category.
        
        MUST FOLLOW THESE RULES:
        1. Each mod must appear in exactly one category (every mod must be categorized, no duplicate mods)
        2. Use ONLY the category names I provided as keys (no new categories) (no extra extraquotation marks or formatting)
        3. Return ONLY a JSON object with categories as keys and arrays of mod names as values, no additional text
        """
    
    # Prepare the request to Groq
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": model,  # Using Llama 3 70B model
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,  # Lower temperature for more consistent results
        "max_tokens": 6000
    }
    
    print(f"Sending request to Groq API...")
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        # Print detailed error information
        if response.status_code != 200:
            try:
                error_data = response.json()
                print(f"Error code: {error_data['error']['code']}")
            except:
                print(f"Raw error response: {response.text}")
            
            response.raise_for_status()  # Raise exception for error status codes
        
        response_data = response.json()
        # print(f"Received response from Groq API: {response_data}")

        if "choices" in response_data and len(response_data["choices"]) > 0:
            groq_response = response_data["choices"][0]["message"]["content"]
            print("Tokens spent on request to Groq API: ", response_data["usage"]["total_tokens"])
            
            # Extract the JSON part from the response
            json_match = re.search(r'```\n(.*?)\n```|(\{.*\})', groq_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1) or json_match.group(2)
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    print(f"Error: Failed to parse JSON from Groq response")
                    print(f"Response: {groq_response}")
                    return None
            else:
                try:
                    # Try to parse the entire response as JSON
                    return json.loads(groq_response)
                except json.JSONDecodeError:
                    print(f"Error: Could not extract JSON from Groq response")
                    print(f"Response: {groq_response}")
                    return None
        else:
            print(f"Error: Unexpected response format from Groq")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Error calling Groq API: {e}")
        return None







def create_categorization_model(categories: List[str], valid_mods: List[str]):
    """Create a dynamic Pydantic model for the categorization response"""
    
    # Create field definitions for each category
    fields = {}
    for category in categories:
        fields[category] = (List[str], Field(default_factory=list, description=f"Mods in {category} category"))
    
    # Create the model dynamically
    CategorizationModel = create_model('CategorizationModel', **fields)
    
    # Add custom validation
    def validate_mods(cls, values):
        all_categorized_mods = []
        for category_mods in values.values():
            all_categorized_mods.extend(category_mods)
        
        # Check for invalid mods
        invalid_mods = [mod for mod in all_categorized_mods if mod not in valid_mods]
        if invalid_mods:
            raise ValueError(f"Invalid mods found: {invalid_mods}")
        
        # Check for duplicates
        if len(all_categorized_mods) != len(set(all_categorized_mods)):
            raise ValueError("Duplicate mods found across categories")
        
        return values
    
    # Add the validator to the model
    CategorizationModel.__validators__ = {'validate_mods': validate_mods}
    
    return CategorizationModel

def validate_with_pydantic(response_data: dict, categories: List[str], valid_mods: List[str]) -> Dict[str, List[str]]:
    """Validate the response using Pydantic and fix common issues"""
    
    try:
        # Create the model
        CategorizationModel = create_categorization_model(categories, valid_mods)
        
        # Try to validate the response
        validated = CategorizationModel(**response_data)
        return validated.model_dump()
        
    except ValidationError as e:
        print(f"Pydantic validation failed: {e}")
        print("Attempting to fix the response...")
        
        # Fix the response programmatically
        fixed_response = fix_categorization_response(response_data, categories, valid_mods)
        
        # Try validation again
        try:
            CategorizationModel = create_categorization_model(categories, valid_mods)
            validated = CategorizationModel(**fixed_response)
            print("Successfully fixed and validated response")
            return validated.dict()
        except ValidationError as e2:
            print(f"Could not fix response: {e2}")
            # Return a basic fallback
            return {}

def fix_categorization_response(response_data: dict, categories: List[str], valid_mods: List[str]) -> Dict[str, List[str]]:
    """Fix common issues in the categorization response"""
    
    # Start with empty categories
    fixed_response = {category: [] for category in categories}
    
    # Process the response
    all_found_mods = set()
    
    for key, value in response_data.items():
        # Normalize the key (remove extra characters, fix capitalization)
        normalized_key = normalize_category_name(key, categories)
        
        if normalized_key and isinstance(value, list):
            # Filter to only valid mods and avoid duplicates
            valid_category_mods = []
            for mod in value:
                if isinstance(mod, str) and mod in valid_mods and mod not in all_found_mods:
                    valid_category_mods.append(mod)
                    all_found_mods.add(mod)
            
            fixed_response[normalized_key].extend(valid_category_mods)
    
    # Put any missing mods in UNSORTED if it exists
    missing_mods = set(valid_mods) - all_found_mods
    if missing_mods and 'UNSORTED' in fixed_response:
        fixed_response['UNSORTED'].extend(list(missing_mods))
        print(f"Added {len(missing_mods)} missing mods to UNSORTED")
    
    return fixed_response

def normalize_category_name(key: str, valid_categories: List[str]) -> str:
    """Try to match a key to a valid category name"""
    
    # Direct match
    if key in valid_categories:
        return key
    
    # Case insensitive match
    key_lower = key.lower()
    for category in valid_categories:
        if category.lower() == key_lower:
            return category
    
    # Fuzzy matching - check if key is contained in any category or vice versa
    for category in valid_categories:
        if key_lower in category.lower() or category.lower() in key_lower:
            return category
    
    # No match found
    print(f"Could not match key '{key}' to any valid category")
    return None

def create_fallback_categorization(query, mod_names):
    """Create a fallback categorization if the Groq API call fails"""
    print("Creating fallback categorization...")
    fallback = {}
    for category in query["categories"]:
        clean_category = re.sub(r'[-|]', '', category).strip()
        fallback[clean_category] = []
    
    # Put all mods in the UNSORTED category as a fallback
    fallback['UNSORTED'] = mod_names
    
    return fallback

def format_json_with_trailing_commas(data, indent=2):
    """
    Format JSON with square brackets on separate lines and trailing commas
    for easier manual editing while maintaining parseable JSON.
    """
    def format_dict(d, current_indent=0):
        if not d:
            return "{}"
        
        spaces = " " * current_indent
        inner_spaces = " " * (current_indent + indent)
        
        lines = ["{"]
        
        for key, value in d.items():
            if isinstance(value, list):
                if not value:
                    lines.append(f'{inner_spaces}"{key}": [\n')
                    lines.append(f'{inner_spaces}],')
                else:
                    lines.append(f'{inner_spaces}"{key}": [')
                    for item in value:
                        lines.append(f'{inner_spaces}  "{item}",')
                    lines.append(f'\n{inner_spaces}],')
            else:
                # Handle other data types if needed
                lines.append(f'{inner_spaces}"{key}": {json.dumps(value)},')
        
        # Remove the trailing comma from the last item
        if lines[-1].endswith(','):
            lines[-1] = lines[-1][:-1]
        
        lines.append(spaces + "}")
        return "\n".join(lines)
    
    return format_dict(data)

def clean_json_for_parsing(json_str):
    """Remove trailing commas before parsing if needed"""
    # Remove trailing commas before ] and }
    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
    return json_str