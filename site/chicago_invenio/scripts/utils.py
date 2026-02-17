import re
import unicodedata

def slugify(text):
    """Convert text to slug format (same as load_as_coms_colls.py)."""
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    # remove punctuation (keep letters, numbers, whitespace and hyphens)
    text = re.sub(r'[^\w\s-]', '', text)
    # replace whitespace/underscores with hyphens and collapse consecutive hyphens
    text = re.sub(r'[\s_]+', '-', text.strip().lower())
    return text.strip('-')