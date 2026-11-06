"""Transparent, rule-based NL/EN query expansion for LinkedIn CSV full-text search.

This is deliberately not a semantic/AI search: it recognizes a limited set of
work-related synonyms. Every conceptual term still needs to match somewhere.
"""
import re

# Keep groups narrow: false positives are more harmful than missed matches.
GROUPS = [
    ("it", "ict", "informatietechnologie", "information technology", "information systems"),
    ("manager", "management", "teamleider", "teamlead", "team lead", "head", "director", "directeur", "leidinggevende"),
    ("overheid", "publieke sector", "public sector", "government", "gemeente", "municipality", "waterschap", "provincie", "rijkswaterstaat", "ministerie"),
    ("architect", "architectuur", "architecture", "architecte"),
    ("security", "cybersecurity", "informatiebeveiliging", "infosec", "cyber"),
    ("cloud", "aws", "azure", "gcp", "cloudplatform"),
    ("kubernetes", "k8s"),
    ("developer", "ontwikkelaar", "programmeur", "software engineer"),
    ("data", "analytics", "data engineering", "gegevens"),
    ("devops", "platform engineering", "sre", "site reliability"),
    ("verandermanagement", "change management", "transformatie", "transformation"),
    ("projectmanager", "projectleider", "project management"),
]

# Do not treat normal small words as mandatory search terms in natural-language queries.
STOPWORDS = {"wie", "ken", "ik", "met", "bij", "een", "de", "het", "en",
             "van", "voor", "in", "op", "aan", "die", "heeft", "hebben",
             "ervaring", "ervaren", "zoek", "iemand", "mensen", "naar"}

def _ftsterm(term):
    # Only pass quoted, safe tokens/phrases to the FTS5 MATCH expression.
    words = re.findall(r"[^\W_]+", term.casefold(), flags=re.UNICODE)
    if not words:
        return ""
    return '"' + " ".join(words) + '"' + ("*" if len(words) == 1 else "")

def query_expression(query):
    """AND user concepts; OR a bounded set of synonyms per concept."""
    tokens = re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
    result = []
    seen_groups = set()
    for term in tokens[:12]:
        if term in STOPWORDS:
            continue
        group_index = next((i for i, group in enumerate(GROUPS)
                            if term in group and " " not in term), None)
        if group_index is not None:
            if group_index in seen_groups:
                continue
            seen_groups.add(group_index)
            options = [_ftsterm(word) for word in GROUPS[group_index]]
            result.append("(" + " OR ".join(filter(None, options)) + ")")
        else:
            result.append(_ftsterm(term))
    return " AND ".join(filter(None, result))

def expanded_query(query):
    tokens = set(re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE))
    return any(any(t in group for t in tokens) for group in GROUPS)
