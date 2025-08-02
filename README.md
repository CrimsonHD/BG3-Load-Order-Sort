# BG3-Load-Order-Sort
Better load order editing interface, sorting and automation.


**Basic mode**: Just a nicer load order interface.
    Includes drag and drop, ctrl and shift multi select, alt-arrow_key selected line movement, single and multi line index setting,
    foldable categories and sub-categories.


**Add Groq key mode**: Automatically sorts unsorted mods.
    The editor reads mod descriptions and provides one button category recommendation, allows making adjustments and one button category population for unsorted mods.


**How to use**:

    - ﻿Put the exe in a folder somewhere
     - If you want them, add category dividers from the nexus dependencies to your load order (not needed for basic mode)
    - ﻿Launch and click the settings button, click Browse LSX and locate your modsettings file (see images), Save the settings
     - Click Load LSX, now you can move mods around, Reset from file or Save Changes (you have to manually save any changes you want to persist)
    
    ﻿- Add new mods (with your mod manager of choice) and put them under the UNSORTED category divider in your load order
        - this allows one button category recommendation/update.
            - First fill out all Settings folder fields first (for some reason the settings window minimizes when file browsing :/), Save the settings 
            - click Generate Mod Data ﻿to extract mod ﻿descriptions, they will be stored in the LOS data folder set in settings 
            - click Generate Sort Recommendations, look them over, ﻿move lines around as ﻿needed with alt-arrow_keys in the right side text editor
            - click Confirm Changes to update ﻿your sort order.

The sort works by comparing the mod descriptions of x randomly chosen mods from each category to the unsorted mods. I should make x variable in case someone has access to models with less stingy rate limits.

If you like my work and want to support it:

[Ko-fi](https://ko-fi.com/crimsonhd)
