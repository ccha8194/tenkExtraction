# run in terminal using: python3 tenkExtraction.py
# will ask for 2 user inputs: url of 10-k and name of output json file
# neccesary packages: pip install requests beautifulsoup4 
# for the user-agent header, SEC requires an email to be provided for some reason.


import re
import json
import requests
import unicodedata
from bs4 import BeautifulSoup
from collections import OrderedDict
from typing import List, Tuple, Dict, Optional
from urllib.parse import urljoin, urlparse
import time
from datetime import datetime

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; SECParser/1.0; <email>)', # SEC requires user-agent to scrape: can be any email 
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'www.sec.gov'
}

SECTION_MAPPINGS = {
    'item_1': [
        'business', 'our business', 'the business', 'overview', 'company overview',
        'general', 'general development of business', 'description of business'
    ],
    'item_1a': [
        'risk factors', 'risks', 'principal risks', 'key risks'
    ],
    'item_1b': [
        'unresolved staff comments', 'unresolved sec staff comments'
    ],
    'item_1c': [
        'cybersecurity', 'cyber security', 'information security', 'security risks',
        'cybersecurity risk management', 'cybersecurity governance', 'cybersecurity threats'
    ],
    'item_2': [
        'properties', 'real estate', 'facilities'
    ],
    'item_3': [
        'legal proceedings', 'litigation', 'legal matters'
    ],
    'item_4': [
        'mine safety disclosures', 'mine safety'
    ],
    'item_5': [
        'market for registrant', 'market for common equity', 'stockholder matters'
    ],
    'item_6': [
        'selected financial data', 'selected consolidated financial data'
    ],
    'item_7': [
        'management\'s discussion and analysis', 'md&a', 'mda', 
        'management discussion and analysis', 'financial condition and results',
        'management\'s discussion', 'results of operations'
    ],
    'item_7a': [
        'quantitative and qualitative disclosures about market risk',
        'market risk', 'quantitative disclosures', 'market risk disclosures'
    ],
    'item_8': [
        'financial statements', 'consolidated financial statements', 'financial statements and supplementary data'
    ],
    'item_9': [
        'changes in and disagreements', 'accounting and financial disclosure'
    ],
    'item_9a': [
        'controls and procedures', 'disclosure controls and procedures'
    ],
    'item_9b': [
        'other information'
    ]
}

# the target sections we want to extract
TARGET_SECTIONS = ['item_1', 'item_1a', 'item_1b', 'item_1c', 'item_7', 'item_7a']

def normalize_anchor_text(text: str) -> str:
    text = unicodedata.normalize('NFKD', text)
    text = text.replace('\xa0', ' ')  # non breaking space 
    text = re.sub(r'[^\w\s]', '', text.lower())  # removes punctuation
    text = re.sub(r'\s+', ' ', text).strip()  # whitespace
    return text

def is_target_item_explicit(text: str) -> Tuple[bool, str]:
    normalized = normalize_anchor_text(text)
    # remove spaces for pattern matching
    no_spaces = re.sub(r'\s+', '', normalized)
    
    # look for item patterns
    item_match = re.search(r'item\s*(\d+)([a-z]?)', normalized)
    if item_match:
        item_num = item_match.group(1)
        item_letter = item_match.group(2) or ''
        item_key = f"item_{item_num}{item_letter}"
        return True, item_key
                
    return False, ""

def is_target_item_semantic(text: str) -> Tuple[bool, str]:
    normalized = normalize_anchor_text(text)
    
    for item_key, variations in SECTION_MAPPINGS.items():
        for variation in variations:
            if variation in normalized:
                return True, item_key
                
    return False, ""

def get_item_sort_key(item_name: str) -> Tuple[int, str]:
    """Convert item name to sortable tuple (number, letter)"""
    match = re.match(r'item_(\d+)([a-z]?)', item_name)
    if match:
        num = int(match.group(1))
        letter = match.group(2) or ''
        return (num, letter)
    return (999, '')  # put unmatched at end

def extract_sections_by_text_search(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """Fallback method: Search for section headers directly in document text"""
    print("Falling back to traditional text-based section detection...")
    
    all_elements = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'span', 'td', 'th'])
    
    found_sections = []
    seen = set()
    
    for element in all_elements:
        text = element.get_text(separator=" ", strip=True)
        if not text or len(text) > 200:  
            continue
            
        is_explicit, item_key = is_target_item_explicit(text)
        if is_explicit and item_key not in seen:
            element_id = f"section_{item_key}_{len(found_sections)}"
            
            if not element.get('id') and not element.get('name'):
                element['id'] = element_id
                target_id = element_id
            else:
                target_id = element.get('id') or element.get('name')
            
            seen.add(item_key)
            found_sections.append((item_key, target_id))
            print(f"  Found section header: '{text[:50]}...' -> {item_key}")
            continue
        
        is_semantic, item_key = is_target_item_semantic(text)
        if is_semantic and item_key not in seen:
            element_id = f"section_{item_key}_{len(found_sections)}"
            
            if not element.get('id') and not element.get('name'):
                element['id'] = element_id
                target_id = element_id
            else:
                target_id = element.get('id') or element.get('name')
            
            seen.add(item_key)
            found_sections.append((item_key, target_id))
            print(f"  Found section header (semantic): '{text[:50]}...' -> {item_key}")
    
    return found_sections

def extract_all_section_anchors(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """Extract ALL Item sections for comprehensive boundary detection"""
    anchors = soup.find_all("a", href=True)
    all_sections = []
    seen = set()
    
    for a in anchors:
        href = a.get("href", "").strip()
        if not href.startswith("#"):
            continue
            
        label_raw = a.get_text(separator=" ", strip=True)
        if not label_raw:
            continue
            
        is_explicit, item_key = is_target_item_explicit(label_raw)
        if is_explicit and item_key not in seen:
            seen.add(item_key)
            all_sections.append((item_key, href.strip("#")))
            continue
            
        is_semantic, item_key = is_target_item_semantic(label_raw)
        if is_semantic and item_key not in seen:
            seen.add(item_key)
            all_sections.append((item_key, href.strip("#")))
    
    if not all_sections:
        print("No standard TOC anchors found, trying text-based section detection...")
        all_sections = extract_sections_by_text_search(soup)
    
    all_sections.sort(key=lambda x: get_item_sort_key(x[0]))
    return all_sections

def find_next_available_section(all_sections: List[Tuple[str, str]], current_section: str) -> Optional[str]:
    """Find the very next section that exists in the document (sequential boundary)"""
    current_sort_key = get_item_sort_key(current_section)
    
    next_sections = []
    for section_name, section_id in all_sections:
        section_sort_key = get_item_sort_key(section_name)
        if section_sort_key > current_sort_key:
            next_sections.append((section_name, section_id, section_sort_key))
    
    if next_sections:
        next_sections.sort(key=lambda x: x[2])
        return next_sections[0][1]  # return section_id
    
    return None

def extract_target_anchors(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """Extract anchors for all sections (targets + boundaries)"""
    anchors = soup.find_all("a", href=True)
    seen = set()
    results = []
    
    for a in anchors:
        href = a.get("href", "").strip()
        if not href.startswith("#"):
            continue
            
        label_raw = a.get_text(separator=" ", strip=True)
        if not label_raw:
            continue
            
        is_explicit, item_key = is_target_item_explicit(label_raw)
        if is_explicit and item_key not in seen:
            seen.add(item_key)
            results.append((item_key, href.strip("#")))
            print(f"  Found explicit: {label_raw} -> {item_key}")
            continue
        
        is_semantic, item_key = is_target_item_semantic(label_raw)
        if is_semantic and item_key not in seen:
            seen.add(item_key)
            results.append((item_key, href.strip("#")))
            print(f"  Found semantic: {label_raw} -> {item_key}")
    
    if not results:
        print("No standard anchors found, trying text-based section detection...")
        results = extract_sections_by_text_search(soup)
    
    return results

def find_section_content_text_based(soup: BeautifulSoup, target_element, next_target_element=None) -> str:
    """Extract content for text-based detection method"""
    collected_text = []
    
    current = target_element.find_next_sibling()
    
    if not current and target_element.parent:
        current = target_element.parent.find_next_sibling()
    
    while current:
        if next_target_element and current == next_target_element:
            break
            
        if hasattr(current, 'get_text'):
            current_text = current.get_text(separator=" ", strip=True)
            if current_text and len(current_text) < 200:  # potential header
                is_explicit, _ = is_target_item_explicit(current_text)
                is_semantic, _ = is_target_item_semantic(current_text)
                if (is_explicit or is_semantic) and current != target_element:
                    break
        
        if hasattr(current, 'get_text'):
            text = current.get_text(separator=' ', strip=True)
            if text and len(text) > 10:  
                collected_text.append(text)
        
        current = current.find_next_sibling()
        
        if not current and hasattr(current, 'parent') and current.parent:
            parent = current.parent
            current = parent.find_next_sibling()
    
    return "\n\n".join(collected_text).strip()

def find_section_content_advanced(soup: BeautifulSoup, target_id: str, next_target_id: str = None) -> str:
    target_el = None
    
    # Strategy 1: look for element with id attribute
    target_el = soup.find(attrs={"id": target_id})
    if not target_el:
        for el in soup.find_all(attrs={"id": True}):
            if el.get("id", "").lower() == target_id.lower():
                target_el = el
                break
    
    # Strategy 2: Look for <a> element with name attribute
    if not target_el:
        target_el = soup.find("a", attrs={"name": target_id})
        if not target_el:
            for el in soup.find_all("a", attrs={"name": True}):
                if el.get("name", "").lower() == target_id.lower():
                    target_el = el
                    break
    
    # Strategy 3: Look for any element with name attribute (not just <a>)
    if not target_el:
        target_el = soup.find(attrs={"name": target_id})
        if not target_el:
            for el in soup.find_all(attrs={"name": True}):
                if el.get("name", "").lower() == target_id.lower():
                    target_el = el
                    break
    
    if not target_el:
        return ""
    
    # find next section element if specified
    next_el = None
    if next_target_id:
        next_el = soup.find(attrs={"id": next_target_id})
        if not next_el:
            next_el = soup.find("a", attrs={"name": next_target_id})
        if not next_el:
            next_el = soup.find(attrs={"name": next_target_id})
        if not next_el:
            for el in soup.find_all(attrs={"id": True}):
                if el.get("id", "").lower() == next_target_id.lower():
                    next_el = el
                    break
            if not next_el:
                for el in soup.find_all(attrs={"name": True}):
                    if el.get("name", "").lower() == next_target_id.lower():
                        next_el = el
                        break
    
    # check if this looks like a text-based detection (ID starts with "section_")
    if target_id.startswith("section_"):
        return find_section_content_text_based(soup, target_el, next_el)
    
    collected_text = []
    
    # special handling for <a name="..."> anchors
    if target_el.name == 'a' and target_el.get('name'):
        current = target_el
        
        if not target_el.get_text(strip=True):
            current = target_el.find_next_sibling()
    else:
        current = target_el.find_next_sibling()
    
    while current and current != next_el:
        if hasattr(current, 'get_text'):
            text = current.get_text(separator=' ', strip=True)
            if text and len(text) > 10:  
                collected_text.append(text)
        current = current.find_next_sibling()
    
    # fallback strategies if no content found
    if not collected_text and target_el.name == 'a':
        parent = target_el.parent
        if parent:
            current = parent.find_next_sibling()
            while current and current != next_el:
                if hasattr(current, 'get_text'):
                    text = current.get_text(separator=' ', strip=True)
                    if text and len(text) > 10:
                        collected_text.append(text)
                current = current.find_next_sibling()
    
    if not collected_text and target_el.name != 'a':
        text = target_el.get_text(separator=' ', strip=True)
        if text and len(text) > 50:
            collected_text.append(text)
    
    if not collected_text and target_el.parent:
        current = target_el.parent.find_next_sibling()
        while current and current != next_el:
            if hasattr(current, 'get_text'):
                text = current.get_text(separator=' ', strip=True)
                if text and len(text) > 10:
                    collected_text.append(text)
            current = current.find_next_sibling()
    
    return "\n\n".join(collected_text).strip()

def extract_div_text_blocks(soup: BeautifulSoup, target_ids: List[Tuple[str, str]]) -> Dict[str, str]:
    if not target_ids:
        return {}
    
    # get ALL sections for comprehensive boundary detection
    print("Mapping all section boundaries...")
    all_sections = extract_all_section_anchors(soup)
    print(f"  Found {len(all_sections)} total sections: {[s[0] for s in all_sections]}")
        
    extracted = {}
    
    # create a dict for easy lookup of section IDs
    section_dict = dict(target_ids)
    
    for label, div_id in target_ids:
        # only extract target sections
        if label not in TARGET_SECTIONS:
            continue
            
        # find the next available section as boundary (sequential stopping)
        next_boundary_id = find_next_available_section(all_sections, label)
        
        print(f"  Extracting {label} (ID: {div_id})...")
        if next_boundary_id:
            # find which section this boundary ID belongs to
            boundary_section = None
            for sec_name, sec_id in all_sections:
                if sec_id == next_boundary_id:
                    boundary_section = sec_name
                    break
            print(f"    Boundary: stops at next available section '{boundary_section}' (ID: {next_boundary_id})")
        else:
            print(f"    Boundary: continues to end of document")
            
        full_text = find_section_content_advanced(soup, div_id, next_boundary_id)
        
        if full_text:
            extracted[label] = full_text
            print(f"    Extracted {len(full_text)} characters")
        else:
            print(f"    No content found for {div_id}")
            target_el = (soup.find(attrs={"id": div_id}) or 
                        soup.find("a", attrs={"name": div_id}) or
                        soup.find(attrs={"name": div_id}))
            if target_el:
                print(f"    Found element: <{target_el.name}> with {target_el.attrs}")
            else:
                print(f"    No element found with id or name '{div_id}'")
    
    return extracted

def fetch_10k_html(url: str) -> BeautifulSoup:
    """Fetch and parse 10-K HTML document"""
    print(f"Fetching 10-K from {url}...")
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.content, "html.parser")

def validate_extracted_content(extracted: Dict[str, str]) -> None:
    """Validate and provide feedback on extracted content"""
    if not extracted:
        print("No content was extracted!")
        return
    
    print(f"\nExtraction Summary:")
    for section in TARGET_SECTIONS:
        if section in extracted:
            content = extracted[section]
            word_count = len(content.split())
            char_count = len(content)
            print(f"  {section}: {word_count:,} words, {char_count:,} characters")
        else:
            print(f"  {section}: NOT FOUND")

def should_use_xbrl_fallback(extracted: Dict[str, str], target_found: List[str]) -> bool:
    """Determine if XBRL fallback should be used based on extraction quality"""
    
    # Check if no TOC anchor links found
    if not extracted:
        print("Using XBRL fallback: No TOC anchor links found")
        return True
    
    # Check if half or less of target items found
    found_count = len([section for section in TARGET_SECTIONS if section in extracted and extracted[section]])
    if found_count <= len(TARGET_SECTIONS) // 2:
        print(f"Using XBRL fallback: Only {found_count}/{len(TARGET_SECTIONS)} target sections found")
        return True
    
    # Check if any section has more than 30,000 words
    for section, content in extracted.items():
        if content and len(content.split()) > 30000:
            print(f"Using XBRL fallback: Section {section} has {len(content.split())} words (>30,000)")
            return True
    
    return False

# XBRL Fallback Parser Class
class XBRLSectionParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; SECParser/1.0; cha.christian.s@gmail.com)'
        })
        self.section_mapping = {
            'item_1': {
                'xbrl_tag': 'us-gaap:BusinessDescription',
                'title': 'Business',
                'patterns': [
                    r'item\s*1\b(?!\s*[a-c])',
                    r'business\s*$',
                    r'item\s*1\s*\.\s*business'
                ]
            },
            'item_1a': {
                'xbrl_tag': 'us-gaap:RiskFactors',
                'title': 'Risk Factors',
                'patterns': [
                    r'item\s*1a\b',
                    r'risk\s*factors',
                    r'item\s*1\s*a\s*\.\s*risk'
                ]
            },
            'item_1b': {
                'xbrl_tag': 'us-gaap:UnresolvedStaffComments',
                'title': 'Unresolved Staff Comments',
                'patterns': [
                    r'item\s*1b\b',
                    r'unresolved\s*staff\s*comments',
                    r'item\s*1\s*b\s*\.\s*unresolved'
                ]
            },
            'item_1c': {
                'xbrl_tag': 'us-gaap:Cybersecurity',
                'title': 'Cybersecurity',
                'patterns': [
                    r'item\s*1c\b',
                    r'cybersecurity',
                    r'item\s*1\s*c\s*\.\s*cybersecurity'
                ]
            },
            'item_7': {
                'xbrl_tag': 'us-gaap:ManagementDiscussionAndAnalysis',
                'title': "Management's Discussion and Analysis",
                'patterns': [
                    r'item\s*7\b(?!\s*a)',
                    r'management\'?s\s*discussion\s*and\s*analysis',
                    r'md&a',
                    r'item\s*7\s*\.\s*management'
                ]
            },
            'item_7a': {
                'xbrl_tag': 'us-gaap:QuantitativeAndQualitativeDisclosuresAboutMarketRisk',
                'title': 'Quantitative and Qualitative Disclosures About Market Risk',
                'patterns': [
                    r'item\s*7a\b',
                    r'quantitative\s*and\s*qualitative\s*disclosures',
                    r'market\s*risk',
                    r'item\s*7\s*a\s*\.\s*quantitative'
                ]
            }
        }

    def clean_text(self, text: str) -> str:
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'&[a-zA-Z]+;', ' ', text)
        text = text.strip()
        return text

    def find_section_boundaries(self, soup: BeautifulSoup) -> Dict[str, Tuple[int, int]]:
        boundaries = {}
        all_text = soup.get_text()
        
        for section_id, section_info in self.section_mapping.items():
            start_pos = None
            
            for pattern in section_info['patterns']:
                matches = list(re.finditer(pattern, all_text, re.IGNORECASE))
                if matches:
                    for match in matches:
                        context_start = max(0, match.start() - 100)
                        context_end = min(len(all_text), match.end() + 100)
                        context = all_text[context_start:context_end]
                        if self._is_section_header(context, match.group()):
                            start_pos = match.start()
                            break
                    if start_pos:
                        break
            
            if start_pos:
                boundaries[section_id] = (start_pos, None)
        
        # Set end positions based on next section starts
        section_positions = sorted([(pos[0], section_id) for section_id, pos in boundaries.items()])
        for i in range(len(section_positions)):
            section_id = section_positions[i][1]
            start_pos = section_positions[i][0]
            if i < len(section_positions) - 1:
                end_pos = section_positions[i + 1][0]
            else:
                end_pos = len(all_text)
            boundaries[section_id] = (start_pos, end_pos)
        
        return boundaries

    def _is_section_header(self, context: str, match_text: str) -> bool:
        header_indicators = [
            r'item\s*\d+[a-c]?\s*\.',
            r'^\s*item\s*\d+[a-c]?\s*',
            r'part\s*[iv]+\s*item\s*\d+[a-c]?'
        ]
        for indicator in header_indicators:
            if re.search(indicator, context, re.IGNORECASE):
                return True
        return False

    def extract_section_content(self, soup: BeautifulSoup, section_id: str, 
                              start_pos: int, end_pos: int) -> str:
        full_text = soup.get_text()
        section_text = full_text[start_pos:end_pos] if end_pos else full_text[start_pos:]
        cleaned_text = self.clean_text(section_text)
        return cleaned_text

    def parse_10k_filing_xbrl(self, soup: BeautifulSoup) -> Dict[str, str]:
        print("Using XBRL pattern-based extraction method...")
        
        boundaries = self.find_section_boundaries(soup)
        extracted = {}
        
        for section_id in TARGET_SECTIONS:
            if section_id in boundaries:
                start_pos, end_pos = boundaries[section_id]
                content = self.extract_section_content(soup, section_id, start_pos, end_pos)
                if content:
                    extracted[section_id] = content
                    word_count = len(content.split())
                    print(f"  Extracted {section_id}: {word_count:,} words")
            else:
                print(f"  {section_id}: NOT FOUND")
        
        return extracted

def main():
    print("SEC 10-K Enhanced Parser with XBRL Fallback")
    print("=" * 50)
    
    url = input("Enter the full URL of the 10-K HTML page: ").strip()
    if not url:
        print("URL is required")
        return
        
    output_file = input("Enter the desired output JSON filename: ").strip()
    if not output_file:
        output_file = "10k_extracted.json"
    
    try:
        soup = fetch_10k_html(url)
        print(f"Successfully loaded HTML document")
    except Exception as e:
        print(f"Failed to fetch HTML: {e}")
        return
    
    # First, try the original TOC anchor method
    print("\nExtracting TOC anchors for all sections...")
    toc_targets = extract_target_anchors(soup)
    
    target_found = [label for label, _ in toc_targets if label in TARGET_SECTIONS]
    print(f"Target sections found: {target_found}")
    
    extracted = {}
    
    if toc_targets:
        print("\nExtracting section content with sequential boundaries...")
        extracted = extract_div_text_blocks(soup, toc_targets)
    
    # Check if we should use XBRL fallback
    if should_use_xbrl_fallback(extracted, target_found):
        print("\n" + "="*50)
        print("SWITCHING TO XBRL FALLBACK METHOD")
        print("="*50)
        
        xbrl_parser = XBRLSectionParser()
        extracted = xbrl_parser.parse_10k_filing_xbrl(soup)
    
    validate_extracted_content(extracted)
    
    if extracted:
        # Simple JSON format without summary
        result = {
            "extraction_method": "xbrl_fallback" if should_use_xbrl_fallback(extracted, target_found) else "toc_anchor",
            "extraction_timestamp": datetime.now().isoformat(),
            "source_url": url,
            "sections": extracted
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nExtraction complete! Data saved to {output_file}")
        
        # print summary (but don't include in JSON)
        total_words = sum(len(content.split()) for content in extracted.values() if content)
        sections_found = len([s for s in extracted.values() if s])
        print(f"\nFinal Summary:")
        print(f"- Method used: {result['extraction_method']}")
        print(f"- Sections found: {sections_found}/{len(TARGET_SECTIONS)}")
        print(f"- Total words: {total_words:,}")
    else:
        print(f"\nno content extracted: probably because it is old, has non traditional structure, or is not the valid html link format")

if __name__ == "__main__":
    main()
