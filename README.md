# BG3-Load-Order-Sort
Load order editing interface with Includes drag and drop, ctrl and shift multi select, single and multi line index setting, foldable categories and sub-categories. Reads mod descriptions and provides one button category recommendation/update for unsorted mods.

 Better load order editing interface, sorting and automation.


Basic mode: Just a nicer load order interface.
    Includes drag and drop, ctrl and shift multi select, alt-arrow_key selected line movement, single and multi line index setting,
    foldable categories and sub-categories.


Add Groq key mode: Automatically sorts unsorted mods.
    The editor reads mod descriptions and provides one button category recommendation, allows making adjustments and one button category population for unsorted mods.

    Adding new mods and putting them under the UNSORTED category divider in your load order allows one
    button category recommendation/update.
    
    First fill out all Settings folder fields first (for some reason the settings window minimizes when file browsing :/) and Generate Mod Data
    to extract mod descriptions, then Generate Sort Recommendations, look them over, move lines around as
    needed with alt-arrow_keys, then Confirm Changes to update your sort order.

The sort works by comparing the mod descriptions of x randomly chosen mods from each category to the unsorted mods. I should make x variable in case someone has access to models with less stingy rate limits.

If you like my work and want to support it:

[Ko-fi](https://ko-fi.com/crimsonhd)
