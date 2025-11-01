import re

def recognize_products(url: str):
    """
    For an URL of a galaxus product, return all relevant information to create a preview of that product.
    """

    pass


def parse_product_id(url: str):
    """
    Extracts the galaxus product id from the url.
    """
    if (not "galaxus" in url) | (not "product" in url):
        return None

    # parse id
    match = re.search(r'-([0-9]{7,})\b', url)
    if match:
        product_id = match.group(1)
        return product_id

    else:
        return None




