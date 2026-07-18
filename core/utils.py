def flatten_dict(data, parent_key: str = "", sep: str = ".") -> dict:
    """
    PROTO-first optimizēts flatten:
    - atbalsta dict, list, tuple, set
    - ignorē None
    - flatteno tikai dict un dict-list kombinācijas
    - listus ar primitīviem ignorē (EcoFlow tos neizmanto)
    - nested dict → parent.child
    - nested list-of-dicts → parent.0.child
    - saglabā 100% PROTO struktūru
    """

    items = {}

    if data is None:
        return items

    # Primitive at root
    if not isinstance(data, (dict, list, tuple, set)):
        if parent_key:
            items[parent_key] = data
        return items

    # -----------------------------
    # DICT
    # -----------------------------
    if isinstance(data, dict):
        for key, value in data.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key

            # Nested dict
            if isinstance(value, dict):
                items.update(flatten_dict(value, new_key, sep))

            # List / tuple / set
            elif isinstance(value, (list, tuple, set)):
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        list_key = f"{new_key}{sep}{index}"
                        items.update(flatten_dict(item, list_key, sep))
                    else:
                        # Repeated primitives (piem. TOU hour slots)
                        items[f"{new_key}{sep}{index}"] = item
                continue

            # Primitive
            else:
                items[new_key] = value

        return items

    # -----------------------------
    # LIST / TUPLE / SET at root
    # -----------------------------
    for index, item in enumerate(data):
        new_key = f"{parent_key}{sep}{index}" if parent_key else str(index)

        if isinstance(item, dict):
            items.update(flatten_dict(item, new_key, sep))
        else:
            items[new_key] = item

    return items
