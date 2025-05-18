import streamlit as st
import re
import string
import time
from collections import defaultdict
import concurrent.futures
import os
import itertools
from typing import Dict, List, Tuple, Set, Optional, Union
import functools
import threading
from dataclasses import dataclass
from enum import Enum

st.set_page_config(
    page_title="Word Pattern Matcher",
    layout="wide",
    initial_sidebar_state="expanded"
)
VOWELS = set("aeiou")
CONSONANTS = set(string.ascii_lowercase) - VOWELS

class PatternType(Enum):
    SIMPLE = "simple"
    EQUATION = "equation"
    ANAGRAM = "anagram"
    COMPOSITE = "composite"
    REVERSE = "reverse"

@dataclass
class VariableDefinition:
    name: str
    min_len: int
    max_len: int
    pattern: str
    is_fixed_length: bool = True

@dataclass
class PatternStructure:
    type: PatternType
    variables: List[Tuple[str, bool]]  # (var_name, is_reversed)
    literals: List[str]
    total_length: int
    original: str

class WordlistCache:
    def __init__(self):
        self.wordlist = []
        self.word_by_length = defaultdict(list)
        self.words_set = set()
        self.name = ""

    def load_wordlist(self, file_path):
        self.name = os.path.basename(file_path)
        self.wordlist = []
        self.word_by_length = defaultdict(list)
        self.words_set = set()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    word = line.strip().lower()
                    if word and word.isalpha():
                        self.wordlist.append(word)
                        self.word_by_length[len(word)].append(word)
                        self.words_set.add(word)
        except FileNotFoundError:
             st.error(f"Error: Wordlist file not found at {file_path}")
             return 0
        except Exception as e:
             st.error(f"Error reading wordlist file {file_path}: {e}")
             return 0


        self.wordlist.sort()
        for length in self.word_by_length:
            self.word_by_length[length].sort()

        return len(self.wordlist)

word_cache = WordlistCache()

st.sidebar.title("Word Pattern Matcher")
st.sidebar.header("Load Wordlist")

script_dir = os.path.dirname(__file__) if "__file__" in locals() else os.getcwd()
default_wordlist_path = os.path.join(script_dir, "default_wordlist.txt")
broda_wordlist_path = os.path.join(script_dir, "broda_wordlist.txt")
broda_exists = os.path.exists(broda_wordlist_path)
    
options = ["Upload custom wordlist", "Use default wordlist"]
if broda_exists:
    options.append("Use Broda wordlist")

wordlist_option = st.sidebar.radio(
    "Select wordlist",
    options
)

loaded_wordlist_path = None
if wordlist_option == "Upload custom wordlist":
    uploaded_file = st.sidebar.file_uploader("Upload your wordlist (.txt)", type=["txt"])
    if uploaded_file is not None:
        temp_path = os.path.join(script_dir, "temp_uploaded_wordlist.txt")
        try:
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            loaded_wordlist_path = temp_path
        except Exception as e:
            st.sidebar.error(f"Failed to save uploaded file: {e}")
    else:
        st.sidebar.info("Please upload a wordlist file (.txt)")

elif wordlist_option == "Use default wordlist":
    if not os.path.exists(default_wordlist_path):
        try:
            with open(default_wordlist_path, "w") as f:
                for word in ["landform", "linoleum", "loom", "logjam", "lipbalm",
                                 ]:
                     f.write(word + "\n")
            st.sidebar.info("Created default wordlist.")
        except Exception as e:
            st.sidebar.error(f"Failed to create default wordlist: {e}")
    loaded_wordlist_path = default_wordlist_path

elif wordlist_option == "Use Broda wordlist":
    if broda_exists:
        loaded_wordlist_path = broda_wordlist_path
    else:
        st.sidebar.error("Broda wordlist selected but not found.")

if loaded_wordlist_path and word_cache.name != os.path.basename(loaded_wordlist_path):
    st.sidebar.info(f"Loading {os.path.basename(loaded_wordlist_path)}...")
    word_count = word_cache.load_wordlist(loaded_wordlist_path)
    if word_count > 0:
        st.sidebar.success(f"Loaded {word_count} words from {os.path.basename(loaded_wordlist_path)}")
    else:
        st.sidebar.error("Failed to load wordlist or wordlist is empty.")
    if wordlist_option == "Upload custom wordlist" and os.path.exists(loaded_wordlist_path):
          try:
              os.remove(loaded_wordlist_path)
          except Exception as e:
              st.sidebar.warning(f"Could not remove temporary file {loaded_wordlist_path}: {e}")

elif not word_cache.wordlist and 'first_run_done' not in st.session_state:
      st.sidebar.warning("No wordlist loaded. Please select or upload one.")
      st.session_state['first_run_done'] = True


with st.sidebar.expander("Advanced Options"):

    use_threading = False
    max_results = st.number_input("Maximum results to display", min_value=10, max_value=10000, value=1000)
    timeout_seconds = st.number_input("Query timeout (seconds)", min_value=5, max_value=2000, value=120)
    use_substrings = st.checkbox("Allow variable values to be any substring (QAT mode)", value=True, help="If checked, variables can be any substring matching the pattern/length, not just dictionary words. Required for QAT-style queries.")

st.title("Word Pattern Matcher")
st.write("""
Search wordlists using patterns and variable equations.
""")


query_input = st.text_area("Enter your query pattern",
                           height=150)

class PatternMatcher:
    def __init__(self, wordlist: List[str], words_set: Set[str], word_by_length: Dict[int, List[str]], use_threading: bool = True, timeout: int = 60, use_substrings: bool = True):
        self.wordlist = wordlist
        self.words_set = words_set
        self.word_by_length = word_by_length
        self.timeout = timeout
        self.start_time = time.time()
        self._regex_cache = {}
        self._pattern_cache = {}
        self._lock = threading.Lock()
        self.use_threading = use_threading
        self.max_workers = min(32, (os.cpu_count() or 1) + 4)
        self.use_substrings = use_substrings

    def _time_check(self):
        if time.time() - self.start_time > self.timeout:
            raise TimeoutError(f"Query exceeded timeout of {self.timeout} seconds.")

    @functools.lru_cache(maxsize=1024)
    def pattern_to_regex(self, pattern: str) -> str:
        if pattern in self._regex_cache:
            return self._regex_cache[pattern]

        # Handle special character classes
        pattern = pattern.replace("#", f"[{''.join(CONSONANTS)}]")
        pattern = pattern.replace("@", f"[{''.join(VOWELS)}]")

        # Handle wildcards and special characters
        regex = ""
        i = 0
        while i < len(pattern):
            char = pattern[i]
            if char == '.':
                regex += '.'
            elif char == '*':
                regex += '.*'
            elif char == '[':
                j = pattern.find(']', i)
                if j != -1:
                    regex += pattern[i:j+1]
                    i = j
                else:
                    regex += re.escape(char)
            elif char == '\\':
                if i + 1 < len(pattern):
                    regex += re.escape(pattern[i+1])
                    i += 1
                else:
                    regex += re.escape(char)
            else:
                regex += re.escape(char)
            i += 1

        final_regex = f"^{regex}$"
        self._regex_cache[pattern] = final_regex
        return final_regex

    def matches_pattern(self, word: str, pattern: str, length_constraint: Optional[Tuple[int, int]] = None) -> bool:
        if length_constraint is not None:
            min_len, max_len = length_constraint
            if not (min_len <= len(word) <= max_len):
                return False

        if pattern == '*': return True
        if not pattern: return not word

        try:
            regex = self.pattern_to_regex(pattern)
            return bool(re.match(regex, word))
        except re.error as e:
            st.warning(f"Invalid regex generated from pattern '{pattern}': {e}")
            return False

    def parse_variable_definition(self, definition: str) -> Optional[VariableDefinition]:
        # Support both formats: A=(3:pattern) and A=(3-5:pattern)
        match = re.match(r'([A-R])=\((\d+)(?:-(\d+))?:(.*)\)', definition)
        if not match:
            match = re.match(r'([A-R])=\((\d+):(.*)\)', definition)
            if not match:
                st.warning(f"Invalid variable definition format: {definition}")
                return None
            var_name, length, pattern = match.groups()
            min_len = max_len = int(length)
        else:
            var_name, min_len_str, max_len_str, pattern = match.groups()
            min_len = int(min_len_str)
            max_len = int(max_len_str) if max_len_str else min_len

        if min_len <= 0 or max_len < min_len:
            st.warning(f"Invalid length in variable definition: {definition}")
            return None

        return VariableDefinition(
            name=var_name,
            min_len=min_len,
            max_len=max_len,
            pattern=pattern if pattern else "*",
            is_fixed_length=(min_len == max_len)
        )

    def parse_pattern_structure(self, pattern: str, variables: Dict[str, VariableDefinition]) -> Optional[PatternStructure]:
        structure = []
        pos = 0
        total_length = 0
        var_refs = []
        literals = []

        while pos < len(pattern):
            self._time_check()
            var_match = re.match(r'(~?)([A-R])', pattern[pos:])
            if var_match:
                reverse_flag, var_name = var_match.groups()
                is_reversed = (reverse_flag == '~')
                
                if var_name not in variables:
                    st.error(f"Variable '{var_name}' used in pattern '{pattern}' but not defined.")
                    return None
                    
                var_info = variables[var_name]
                if not var_info.is_fixed_length:
                    st.warning(f"Variable '{var_name}' must have fixed length for pattern matching.")
                    return None
                    
                var_refs.append((var_name, is_reversed))
                total_length += var_info.min_len
                pos += len(reverse_flag) + len(var_name)
            else:
                literal_char = pattern[pos]
                literals.append(literal_char)
                total_length += 1
                pos += 1

        return PatternStructure(
            type=self._determine_pattern_type(pattern, var_refs),
            variables=var_refs,
            literals=literals,
            total_length=total_length,
            original=pattern
        )

    def _determine_pattern_type(self, pattern: str, var_refs: List[Tuple[str, bool]]) -> PatternType:
        if pattern.startswith('/'):
            return PatternType.ANAGRAM
        elif any(is_reversed for _, is_reversed in var_refs):
            return PatternType.REVERSE
        elif len(var_refs) > 1:
            return PatternType.COMPOSITE
        else:
            return PatternType.SIMPLE

    def solve_equation(self, variables: Dict[str, VariableDefinition], patterns: List[str]) -> List[Tuple[str, Optional[str], Dict[str, str]]]:
        self.start_time = time.time()
        results = []

        if not patterns or not variables:
            st.warning("Equation solver requires both variables and patterns.")
            return []

        # Parse all patterns into structures
        pattern_structures = []
        for pattern in patterns:
            structure = self.parse_pattern_structure(pattern, variables)
            if structure:
                pattern_structures.append(structure)
            else:
                return []

        # Start with the first pattern
        first_structure = pattern_structures[0]
        first_matches = self._find_matches_for_structure(first_structure, variables)

        # For each match of the first pattern, check if it satisfies all other patterns
        for word, decomp in first_matches:
            self._time_check()
            all_patterns_match = True
            other_words = []

            for structure in pattern_structures[1:]:
                constructed_word = self._construct_word_from_structure(structure, decomp)
                if not constructed_word or constructed_word not in self.words_set:
                    all_patterns_match = False
                    break
                other_words.append(constructed_word)

            if all_patterns_match:
                results.append((word, other_words[0] if other_words else None, decomp))

        return results

    def _find_matches_for_structure(self, structure: PatternStructure, variables: Dict[str, VariableDefinition]) -> List[Tuple[str, Dict[str, str]]]:
        matches = []
        candidate_words = self.word_by_length.get(structure.total_length, [])

        for word in candidate_words:
            self._time_check()
            current_pos = 0
            decomp = {}
            possible = True

            for var_name, is_reversed in structure.variables:
                var_info = variables[var_name]
                var_len = var_info.min_len
                part = word[current_pos : current_pos + var_len]
                part_to_check = part[::-1] if is_reversed else part

                if not self.matches_pattern(part_to_check, var_info.pattern, length_constraint=(var_len, var_len)):
                    possible = False
                    break

                decomp[var_name] = part_to_check
                current_pos += var_len

            for literal in structure.literals:
                if current_pos >= len(word) or word[current_pos] != literal:
                    possible = False
                    break
                current_pos += 1

            if possible and current_pos == len(word):
                matches.append((word, decomp))

        return matches

    def _construct_word_from_structure(self, structure: PatternStructure, decomp: Dict[str, str]) -> Optional[str]:
        try:
            word = ""
            for var_name, is_reversed in structure.variables:
                if var_name not in decomp:
                    return None
                val = decomp[var_name]
                word += val[::-1] if is_reversed else val

            for literal in structure.literals:
                word += literal

            return word
        except Exception as e:
            st.error(f"Error constructing word: {e}")
            return None

    def execute_query(self, query: str) -> Tuple[Optional[List[Tuple[str, Optional[str], Dict[str, str]]]], str]:
        self.start_time = time.time()
        self._regex_cache = {}
        raw_parts = query.strip().split(';')
        parts = [p.strip() for p in raw_parts if p.strip()]

        variable_defs_raw = []
        search_patterns_raw = []
        variables = {}

        # Parse variable definitions and search patterns
        for part in parts:
            if '=' in part and part[0].isalpha() and part[0].isupper() and part[0] <= 'R':
                variable_defs_raw.append(part)
            else:
                search_patterns_raw.append(part)

        # Parse variable definitions
        for v_def_str in variable_defs_raw:
            self._time_check()
            parsed_var = self.parse_variable_definition(v_def_str)
            if parsed_var:
                variables[parsed_var.name] = parsed_var
            else:
                st.warning(f"Skipping invalid variable definition: {v_def_str}")

        is_equation_query = bool(variables) and bool(search_patterns_raw)
        is_anagram_query = any(p.startswith('/') for p in search_patterns_raw)

        try:
            if is_equation_query:
                # Handle complex equation queries
                if len(search_patterns_raw) > 1:
                    # Multiple patterns with variables
                    results = self._handle_composite_pattern(search_patterns_raw, variables)
                    return results, "equation"
                else:
                    # Single pattern with variables
                    pattern = search_patterns_raw[0]
                    if any('~' in var for var in re.findall(r'(~?[A-R])', pattern)):
                        # Pattern contains reversed variables
                        results = self._handle_reverse_pattern(pattern, variables)
                        return results, "equation"
                    else:
                        # Simple pattern with variables
                        results = self._handle_complex_pattern(pattern, variables)
                        return results, "equation"

            elif len(search_patterns_raw) == 1:
                pattern = search_patterns_raw[0]
                if pattern.startswith('/'):
                    # Anagram pattern
                    matches = self.process_anagram_pattern(pattern)
                    return [(m, None, {}) for m in matches], "anagram"
                else:
                    # Simple pattern
                    matches = self.find_matches_simple_pattern(pattern)
                    return [(m, None, {}) for m in matches], "simple"

            elif len(search_patterns_raw) > 1:
                # Multiple patterns without variables
                st.warning("Handling multiple non-equation patterns via intersection.")
                common_matches = None

                for pattern in search_patterns_raw:
                    self._time_check()
                    current_matches = set()
                    if pattern.startswith('/'):
                        matches_list = self.process_anagram_pattern(pattern)
                        if matches_list is not None:
                            current_matches = set(matches_list)
                    else:
                        matches_list = self.find_matches_simple_pattern(pattern)
                        current_matches = set(matches_list)

                    if common_matches is None:
                        common_matches = current_matches
                    else:
                        common_matches &= current_matches

                    if not common_matches:
                        break

                if common_matches is not None:
                    return [(m, None, {}) for m in sorted(list(common_matches))], "intersection"
            else:
                st.info("Query contains only variable definitions. To see matching words, add the variable name(s) as patterns (e.g., A; B;).")
                return [], "definition_only"

        except TimeoutError:
            st.error(f"Query timed out after {self.timeout} seconds.")
            return None, "timeout"
        except Exception as e:
            st.error(f"An error occurred during query execution: {e}")
            import traceback
            st.error(traceback.format_exc())
            return [], "error"

        return [], "unknown"

    def process_anagram_pattern(self, pattern_str: str) -> Optional[List[str]]:
        if not pattern_str.startswith('/'):
            return None

        self._time_check()

        content = pattern_str[1:]
        dots = content.count('.')
        stars = content.count('*')
        base_letters = sorted([c for c in content if c.isalpha()])
        base_counts = defaultdict(int)
        for char in base_letters:
            base_counts[char] += 1

        matches = []

        min_len = len(base_letters) + dots
        max_len = None if stars > 0 else len(base_letters) + dots

        candidate_words = []
        if max_len is not None:
            if min_len == max_len:
                candidate_words = self.word_by_length.get(min_len, [])
            else:
                for length in range(min_len, max_len + 1):
                    candidate_words.extend(self.word_by_length.get(length, []))
        else:
            for length, words in self.word_by_length.items():
                if length >= min_len:
                    candidate_words.extend(words)

        for i, word in enumerate(candidate_words):
            if i % 1000 == 0: self._time_check()

            if max_len is not None and len(word) != max_len:
                continue
            if len(word) < min_len:
                continue

            word_counts = defaultdict(int)
            possible = True
            for char in word:
                word_counts[char] += 1

            for char, count in base_counts.items():
                if word_counts[char] < count:
                    possible = False
                    break
            if not possible:
                continue

            if stars == 0:
                extra_letters = len(word) - len(base_letters)
                if extra_letters != dots:
                    possible = False

            if possible:
                matches.append(word)

        return matches

    def find_matches_simple_pattern(self, pattern_str: str) -> List[str]:
        self._time_check()
        length_constraint, clean_pattern = self.length_constraint_from_pattern(pattern_str)

        matches = []
        candidate_words = []

        if length_constraint:
            min_len, max_len = length_constraint
            for length in range(min_len, max_len + 1):
                candidate_words.extend(self.word_by_length.get(length, []))
        else:
            candidate_words = self.wordlist

        if not candidate_words: return []

        try:
            regex = self.pattern_to_regex(clean_pattern)
            compiled_regex = re.compile(regex)
        except re.error as e:
            st.error(f"Invalid pattern leads to regex error: {clean_pattern} -> {e}")
            return []

        for i, word in enumerate(candidate_words):
            if i % 2000 == 0: self._time_check()

            if compiled_regex.match(word):
                matches.append(word)

        return matches

    def length_constraint_from_pattern(self, pattern_str):
        match = re.match(r'^(\d+):(.*)', pattern_str)
        if match:
            length, rest_pattern = match.groups()
            length = int(length)
            if length > 0:
                 return (length, length), rest_pattern
            else:
                 st.warning(f"Invalid exact length constraint: {pattern_str}")
                 return None, pattern_str

        match = re.match(r'^(\d+)-(\d+):(.*)', pattern_str)
        if match:
            min_l, max_l, rest_pattern = match.groups()
            min_len, max_len = int(min_l), int(max_l)
            if 0 < min_len <= max_len:
                 return (min_len, max_len), rest_pattern
            else:
                 st.warning(f"Invalid range length constraint: {pattern_str}")
                 return None, pattern_str

        return None, pattern_str

    def _parallel_process_pattern(self, pattern: str, variables: Dict[str, VariableDefinition]) -> List[Tuple[str, Dict[str, str]]]:
        structure = self.parse_pattern_structure(pattern, variables)
        if not structure:
            return []

        matches = []
        candidate_words = self.word_by_length.get(structure.total_length, [])

        def process_chunk(chunk: List[str]) -> List[Tuple[str, Dict[str, str]]]:
            chunk_matches = []
            for word in chunk:
                current_pos = 0
                decomp = {}
                possible = True

                for var_name, is_reversed in structure.variables:
                    var_info = variables[var_name]
                    var_len = var_info.min_len
                    part = word[current_pos : current_pos + var_len]
                    part_to_check = part[::-1] if is_reversed else part

                    if not self.matches_pattern(part_to_check, var_info.pattern, length_constraint=(var_len, var_len)):
                        possible = False
                        break

                    decomp[var_name] = part_to_check
                    current_pos += var_len

                for literal in structure.literals:
                    if current_pos >= len(word) or word[current_pos] != literal:
                        possible = False
                        break
                    current_pos += 1

                if possible and current_pos == len(word):
                    chunk_matches.append((word, decomp))

            return chunk_matches

        if self.use_threading and len(candidate_words) > 1000:
            chunk_size = max(1000, len(candidate_words) // self.max_workers)
            chunks = [candidate_words[i:i + chunk_size] for i in range(0, len(candidate_words), chunk_size)]
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(process_chunk, chunk) for chunk in chunks]
                for future in concurrent.futures.as_completed(futures):
                    matches.extend(future.result())
        else:
            matches = process_chunk(candidate_words)

        return matches

    def _validate_pattern_structure(self, structure: PatternStructure, variables: Dict[str, VariableDefinition]) -> bool:
        # Check if all variables are defined
        for var_name, _ in structure.variables:
            if var_name not in variables:
                st.error(f"Variable '{var_name}' used in pattern '{structure.original}' but not defined.")
                return False

        # Check if all variables have fixed lengths
        for var_name, _ in structure.variables:
            var_info = variables[var_name]
            if not var_info.is_fixed_length:
                st.warning(f"Variable '{var_name}' must have fixed length for pattern matching.")
                return False

        return True

    def _optimize_pattern_order(self, patterns: List[str], variables: Dict[str, VariableDefinition]) -> List[str]:
        # Sort patterns by complexity and length to optimize matching
        pattern_structures = []
        for pattern in patterns:
            structure = self.parse_pattern_structure(pattern, variables)
            if structure:
                pattern_structures.append((pattern, structure))

        # Sort by:
        # 1. Number of variables (fewer first)
        # 2. Total length (shorter first)
        # 3. Number of literals (more first)
        pattern_structures.sort(key=lambda x: (
            len(x[1].variables),
            x[1].total_length,
            -len(x[1].literals)
        ))

        return [p[0] for p in pattern_structures]

    def _format_result(self, result: Tuple[str, Optional[str], Dict[str, str]], pattern_type: str) -> str:
        word1, word2, decomp = result
        if pattern_type == "equation":
            if word2:
                decomp_str = " - ".join(f"{k}={v}" for k, v in sorted(decomp.items()))
                return f"{word1} / {word2}    ({decomp_str})"
            else:
                decomp_str = " - ".join(f"{k}={v}" for k, v in sorted(decomp.items()))
                return f"{word1}    ({decomp_str})"
        else:
            return word1

    def _optimize_word_candidates(self, pattern: str, variables: Dict[str, VariableDefinition]) -> List[str]:
        """Optimize the list of candidate words based on pattern constraints."""
        structure = self.parse_pattern_structure(pattern, variables)
        if not structure:
            return []

        # Get all possible lengths for each variable
        var_lengths = {}
        for var_name, _ in structure.variables:
            var_info = variables[var_name]
            var_lengths[var_name] = (var_info.min_len, var_info.max_len)

        # Calculate total length range
        min_total_len = sum(min_len for min_len, _ in var_lengths.values()) + len(structure.literals)
        max_total_len = sum(max_len for _, max_len in var_lengths.values()) + len(structure.literals)

        # Get all words within the length range
        candidates = []
        for length in range(min_total_len, max_total_len + 1):
            candidates.extend(self.word_by_length.get(length, []))

        return candidates

    def _precompute_pattern_matches(self, pattern: str, variables: Dict[str, VariableDefinition]) -> Dict[str, Set[str]]:
        """Precompute matches for each variable in the pattern."""
        structure = self.parse_pattern_structure(pattern, variables)
        if not structure:
            return {}

        matches = {}
        for var_name, is_reversed in structure.variables:
            var_info = variables[var_name]
            var_matches = set()

            for length in range(var_info.min_len, var_info.max_len + 1):
                for word in self.word_by_length.get(length, []):
                    if self.matches_pattern(word, var_info.pattern, length_constraint=(length, length)):
                        var_matches.add(word)

            matches[var_name] = var_matches

        return matches

    def _validate_variable_constraints(self, variables: Dict[str, VariableDefinition]) -> bool:
        """Validate that all variable constraints are consistent."""
        # Check for overlapping variable names
        var_names = set(variables.keys())
        if len(var_names) != len(variables):
            st.error("Duplicate variable names found.")
            return False

        # Check for valid variable names (A-R)
        for name in var_names:
            if not (len(name) == 1 and 'A' <= name <= 'R'):
                st.error(f"Invalid variable name: {name}. Must be a single letter A-R.")
                return False

        # Check for valid patterns
        for var_info in variables.values():
            try:
                self.pattern_to_regex(var_info.pattern)
            except re.error as e:
                st.error(f"Invalid pattern for variable {var_info.name}: {e}")
                return False

        return True

    def _optimize_pattern_matching(self, pattern: str, variables: Dict[str, VariableDefinition]) -> List[Tuple[str, Dict[str, str]]]:
        """Optimize pattern matching by using precomputed matches and early filtering."""
        structure = self.parse_pattern_structure(pattern, variables)
        if not structure:
            return []

        # Precompute matches for each variable
        var_matches = self._precompute_pattern_matches(pattern, variables)
        if not var_matches:
            return []

        # Get optimized candidate words
        candidates = self._optimize_word_candidates(pattern, variables)
        if not candidates:
            return []

        matches = []
        for word in candidates:
            self._time_check()
            current_pos = 0
            decomp = {}
            possible = True

            for var_name, is_reversed in structure.variables:
                var_info = variables[var_name]
                var_len = var_info.min_len
                part = word[current_pos : current_pos + var_len]
                part_to_check = part[::-1] if is_reversed else part

                # Early filtering using precomputed matches
                if part_to_check not in var_matches[var_name]:
                    possible = False
                    break

                decomp[var_name] = part_to_check
                current_pos += var_len

            for literal in structure.literals:
                if current_pos >= len(word) or word[current_pos] != literal:
                    possible = False
                    break
                current_pos += 1

            if possible and current_pos == len(word):
                matches.append((word, decomp))

        return matches

    def _handle_complex_pattern(self, pattern: str, variables: Dict[str, VariableDefinition]) -> List[Tuple[str, Optional[str], Dict[str, str]]]:
        """Handle patterns with multiple variables and literals using optimized matching."""
        if not self._validate_variable_constraints(variables):
            return []

        matches = self._optimize_pattern_matching(pattern, variables)
        return [(m[0], None, m[1]) for m in matches]

    def _handle_reverse_pattern(self, pattern: str, variables: Dict[str, VariableDefinition]) -> List[Tuple[str, Optional[str], Dict[str, str]]]:
        """Handle patterns with reversed variables using optimized matching."""
        if not self._validate_variable_constraints(variables):
            return []

        matches = self._optimize_pattern_matching(pattern, variables)
        results = []

        for word, decomp in matches:
            reversed_word = ""
            for var_name, is_reversed in self.parse_pattern_structure(pattern, variables).variables:
                val = decomp[var_name]
                reversed_word += val[::-1] if is_reversed else val
            for literal in self.parse_pattern_structure(pattern, variables).literals:
                reversed_word += literal

            if reversed_word in self.words_set:
                results.append((word, reversed_word, decomp))

        return results

    def _all_possible_variable_values(self, var: VariableDefinition) -> List[str]:
        """Generate all possible values for a variable, matching its pattern and length constraints."""
        results = []
        if self.use_substrings:
            for length in range(var.min_len, var.max_len + 1):
                for w in self.wordlist:
                    if len(w) < length:
                        continue
                    for i in range(len(w) - length + 1):
                        candidate = w[i:i+length]
                        if self.matches_pattern(candidate, var.pattern, length_constraint=(length, length)):
                            results.append(candidate)
            return list(set(results))
        else:
            for length in range(var.min_len, var.max_len + 1):
                for word in self.word_by_length.get(length, []):
                    if self.matches_pattern(word, var.pattern, length_constraint=(length, length)):
                        results.append(word)
            return list(set(results))

    def _handle_composite_pattern(self, patterns: List[str], variables: Dict[str, VariableDefinition]) -> List[Tuple[str, Optional[str], Dict[str, str]]]:
        """QAT-style: If substring mode is enabled, always use full product. Otherwise, use optimized driver pattern."""
        if not self._validate_variable_constraints(variables):
            return []

        if self.use_substrings:
            # QAT-style: try all possible substrings for each variable
            var_names = sorted(variables.keys())
            var_domains = [self._all_possible_variable_values(variables[name]) for name in var_names]
            if not all(var_domains):
                return []
            pattern_structures = [self.parse_pattern_structure(p, variables) for p in patterns]
            if not all(pattern_structures):
                return []
            results = []
            for values in itertools.product(*var_domains):
                self._time_check()
                decomp = dict(zip(var_names, values))
                all_words = []
                for structure in pattern_structures:
                    word = ""
                    for var_name, is_reversed in structure.variables:
                        val = decomp[var_name]
                        word += val[::-1] if is_reversed else val
                    for literal in structure.literals:
                        word += literal
                    if word not in self.words_set:
                        break
                    all_words.append(word)
                else:
                    results.append((all_words[0], all_words[1] if len(all_words) > 1 else None, decomp))
                    if len(results) > 10000:
                        break
            return results
        else:
            # Find the pattern with the most literals/longest length
            pattern_structures = [self.parse_pattern_structure(p, variables) for p in patterns]
            if not all(pattern_structures):
                return []
            driver_idx = max(range(len(pattern_structures)), key=lambda i: (len(pattern_structures[i].literals), pattern_structures[i].total_length))
            driver_pattern = patterns[driver_idx]
            driver_structure = pattern_structures[driver_idx]
            other_patterns = [p for i,p in enumerate(patterns) if i != driver_idx]
            other_structures = [s for i,s in enumerate(pattern_structures) if i != driver_idx]
            matches = self._optimize_pattern_matching(driver_pattern, variables)
            results = []
            for word, decomp in matches:
                self._time_check()
                all_ok = True
                for structure in other_structures:
                    candidate = self._construct_word_from_structure(structure, decomp)
                    if not candidate or candidate not in self.words_set:
                        all_ok = False
                        break
                if all_ok:
                    results.append((word, None, decomp))
                    if len(results) > 10000:
                        break
            return results


def format_results(results: Optional[List[Tuple[str, Optional[str], Dict[str, str]]]], result_type: str, max_disp: int) -> str:
    if results is None:
        return "Query execution timed out."
    if not results and result_type != "definition_only":
        return "No matches found."
    if not results and result_type == "definition_only":
        return ""

    num_results = len(results)
    output = [f"Found {num_results} matches:"]
    output.append("---")

    displayed_count = 0
    if result_type == "equation":
        for res_tuple in results:
            if displayed_count >= max_disp: break
            word1, word2, decomp = res_tuple
            decomp_parts = [f"{k}={v}" for k, v in sorted(decomp.items())]
            decomp_str = " - ".join(decomp_parts)

            if word2 is None:
                output.append(f"{word1}    ({decomp_str})")
            else:
                output.append(f"{word1} / {word2}    ({decomp_str})")
            displayed_count += 1
    else:
        for res_tuple in results:
            if displayed_count >= max_disp: break
            word, _, _ = res_tuple
            output.append(word)
            displayed_count += 1

    if num_results > max_disp:
        output.append(f"\n... (displaying {max_disp} of {num_results} results)")

    return "\n".join(output)


if st.button("Execute Search", key="execute_button"):
    query = query_input
    if not query:
        st.warning("Please enter a query pattern.")
    elif not word_cache.wordlist:
         st.error("No wordlist is loaded. Please select or upload a wordlist from the sidebar.")
    else:
        with st.spinner("Searching... This may take time for complex queries."):
             start_exec_time = time.time()
             matcher = PatternMatcher(
                 word_cache.wordlist,
                 word_cache.words_set,
                 word_cache.word_by_length,
                 timeout=timeout_seconds,
                 use_substrings=use_substrings
             )
             results_data, result_type = matcher.execute_query(query)
             end_exec_time = time.time()
             execution_time = end_exec_time - start_exec_time

             if results_data is not None:
                  formatted_output = format_results(results_data, result_type, max_results)
                  result_prefix = f"Search completed in {execution_time:.2f} seconds.\n\n"
                  st.text_area("Results", result_prefix + formatted_output, height=400, key="results_area")
             else:
                  st.text_area("Results", f"Search timed out after {timeout_seconds} seconds.", height=50, key="results_area_timeou")
