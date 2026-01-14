original_string = "17\TenderDoc-2009914322.pdf"
delimiter = "\\"

# To remove the delimiter and everything before it (first occurrence)
parts = original_string.split(delimiter, 1)
result_remove_delimiter = parts[1] if len(parts) > 1 else original_string
print(f"Removing delimiter: {original_string.split("\\", 1)[1]}")