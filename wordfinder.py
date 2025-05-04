import streamlit as st
import re
import string
import time
from collections import defaultdict
import concurrent.futures
import os
import itertools

st.set_page_config(
    page_title="Word Pattern Matcher",
    layout="wide",
    initial_sidebar_state="expanded"
)
VOWELS = set("aeiou")
CONSONANTS = set(string.ascii_lowercase) - VOWELS

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
if not broda_exists:
    st.sidebar.warning(f"Broda wordlist (broda_wordlist.txt) not found in script directory.")

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
    timeout_seconds = st.number_input("Query timeout (seconds)", min_value=5, max_value=600, value=120)

st.title("Word Pattern Matcher")
st.write("""
Search wordlists using patterns and variable equations.
""")


query_input = st.text_area("Enter your query pattern",
                           height=150)

class PatternMatcher:
    def __init__(self, wordlist, words_set, word_by_length, use_threading=True, timeout=60):
        self.wordlist = wordlist
        self.words_set = words_set
        self.word_by_length = word_by_length
        self.timeout = timeout
        self.start_time = time.time()
        self._regex_cache = {}

    def _time_check(self):
        if time.time() - self.start_time > self.timeout:
            raise TimeoutError(f"Query exceeded timeout of {self.timeout} seconds.")

    def pattern_to_regex(self, pattern):
        if pattern in self._regex_cache:
             return self._regex_cache[pattern]

        pattern = pattern.replace("#", f"[{''.join(CONSONANTS)}]")
        pattern = pattern.replace("@", f"[{''.join(VOWELS)}]")

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

    def matches_pattern(self, word, pattern, length_constraint=None):
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

    def parse_variable_definition(self, definition):
        match = re.match(r'([A-R])=\((\d+)(?:-(\d+))?:(.*)\)', definition)
        if not match:
             match = re.match(r'([A-R])=\((\d+):(.*)\)', definition)
             if not match:
                 st.warning(f"Invalid variable definition format: {definition}")
                 return None
             var_name, length, pattern = match.groups()
             min_len = int(length)
             max_len = int(length)
        else:
             var_name, min_len_str, max_len_str, pattern = match.groups()
             min_len = int(min_len_str)
             max_len = int(max_len_str) if max_len_str else min_len

        if min_len <= 0 or max_len < min_len:
             st.warning(f"Invalid length in variable definition: {definition}")
             return None

        return {
            'var_name': var_name,
            'min_len': min_len,
            'max_len': max_len,
            'pattern': pattern if pattern else "*"
        }

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

    def process_anagram_pattern(self, pattern_str):
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
                     candidate_words.extend(self.word_by_length.get(length,[]))
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

    def find_matches_simple_pattern(self, pattern_str):
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


    def solve_equation(self, variables, patterns):
        self.start_time = time.time()
        results = []

        if not patterns:
            st.warning("Equation solver called with no patterns to match.")
            return []
        if not variables:
             st.warning("Equation solver called with no variables defined.")
             return []
        if len(patterns) == 1:
            pattern = patterns[0]
            results_single = []
            var_refs = re.findall(r'(~?[A-R])', pattern)
            if "".join(var_refs).replace('~','') == pattern.replace('~',''):
                 total_len = 0
                 current_vars = {}
                 valid_structure = True
                 var_details = []

                 try:
                     pos = 0
                     while pos < len(pattern):
                         self._time_check()
                         match = re.match(r'(~?)([A-R])', pattern[pos:])
                         if not match:
                              valid_structure = False; break

                         ref, name = match.groups()
                         is_reversed = (ref == '~')
                         if name not in variables:
                              st.error(f"Variable '{name}' used in pattern '{pattern}' but not defined.")
                              return []

                         var_info = variables[name]
                         min_l, max_l, p = var_info['min_len'], var_info['max_len'], var_info['pattern']
                         if min_l != max_l:
                              st.warning(f"Equation solver currently requires fixed lengths for variables in patterns. Variable '{name}' has range {min_l}-{max_l}.")

                              return []
                         var_len = min_l
                         total_len += var_len
                         current_vars[name] = var_info
                         var_details.append({'name': name, 'len': var_len, 'pattern': p, 'reversed': is_reversed})

                         pos += len(ref) + len(name)

                 except TimeoutError as e: raise e
                 except Exception as e:
                     st.error(f"Error parsing pattern '{pattern}': {e}")
                     valid_structure = False

                 if valid_structure:

                     for word in self.word_by_length.get(total_len, []):
                          self._time_check()
                          current_pos = 0
                          decomp = {}
                          possible = True
                          for vd in var_details:
                              part = word[current_pos : current_pos + vd['len']]
                              part_to_check = part[::-1] if vd['reversed'] else part
                              if not self.matches_pattern(part_to_check, vd['pattern'], length_constraint=(vd['len'], vd['len'])):
                                  possible = False; break
                              decomp[vd['name']] = part_to_check
                              current_pos += vd['len']

                          if possible:
                              results_single.append((word, None, decomp))

                 return results_single

            else:

                 st.warning(f"Equation solver currently only supports patterns made purely of variable references (like ABC or ~A). Pattern '{pattern}' is not supported in equation mode.")
                 return []

        elif len(patterns) == 2:
             p1_str, p2_str = patterns[0], patterns[1]
             results_paired = []
             handled = False

             match1 = re.match(r'^([A-R])$', p1_str)
             match2 = re.match(r'^~([A-R])$', p2_str)
             if match1 and match2 and match1.group(1) == match2.group(1):
                 var_name = match1.group(1)
                 if var_name not in variables: st.error(f"Variable '{var_name}' not defined."); return []
                 var_info = variables[var_name]
                 min_l, max_l, p = var_info['min_len'], var_info['max_len'], var_info['pattern']

                 candidates_A = []
                 for length in range(min_l, max_l + 1):
                      for word in self.word_by_length.get(length, []):
                           self._time_check()
                           if self.matches_pattern(word, p, length_constraint=(length, length)):
                                candidates_A.append(word)

                 candidate_set = set(candidates_A)
                 found_pairs = set()

                 for word1 in candidates_A:
                      self._time_check()
                      word2 = word1[::-1]
                      if word1 == word2: continue
                      if word2 in candidate_set:
                          pair = tuple(sorted((word1, word2)))
                          if pair not in found_pairs:
                               results_paired.append( (word1, word2, {var_name: word1}) )
                               found_pairs.add(pair)
                 handled = True

             vars1 = re.findall(r'(~?[A-R])', p1_str)
             vars2 = re.findall(r'(~?[A-R])', p2_str)


             if (len(vars1) > 0 and len(vars1) == len(vars2) and
                   "".join(vars1).replace('~','') == p1_str.replace('~','') and
                   "".join(vars2).replace('~','') == p2_str.replace('~','') and
                   [v.replace('~','') for v in vars1] == [v.replace('~','') for v in vars2][::-1]):


                  lengths = {}
                  total_len = 0
                  var_map = {}
                  structure1 = []

                  valid_config = True
                  try:
                      current_pos = 0
                      for ref in vars1:
                          self._time_check()
                          is_reversed = ref.startswith('~')
                          name = ref.replace('~','')
                          if name not in variables:
                              st.error(f"Variable '{name}' used in '{p1_str}' but not defined.")
                              valid_config = False; break

                          v_info = variables[name]
                          v_min, v_max = v_info['min_len'], v_info['max_len']
                          if v_min != v_max:
                               st.warning(f"Equation solver requires fixed length variables currently. '{name}' has range {v_min}-{v_max}.")
                               valid_config = False; break
                          v_len = v_min
                          v_pat = v_info['pattern']

                          lengths[name] = v_len
                          total_len += v_len
                          var_map[name] = {'len': v_len, 'pattern': v_pat}
                          structure1.append({'name': name, 'len': v_len, 'pattern': v_pat, 'reversed': is_reversed})

                  except TimeoutError as e: raise e
                  except Exception as e: st.error(f"Error processing structure: {e}"); valid_config = False

                  if valid_config:

                       found_decompositions = set()
                       for word1 in self.word_by_length.get(total_len, []):
                            self._time_check()
                            current_pos = 0
                            parts = {}
                            part_list = []
                            possible_decomp = True
                            for s_info in structure1:
                                name = s_info['name']
                                l = s_info['len']
                                p = s_info['pattern']
                                rev = s_info['reversed']

                                segment = word1[current_pos : current_pos + l]
                                segment_to_check = segment[::-1] if rev else segment

                                if not self.matches_pattern(segment_to_check, p, length_constraint=(l,l)):
                                    possible_decomp = False; break

                                parts[name] = segment_to_check
                                part_list.append(segment)
                                current_pos += l

                            if not possible_decomp:
                                continue
                            word2 = ""
                            try:
                                for ref2 in vars2:
                                    is_reversed2 = ref2.startswith('~')
                                    name2 = ref2.replace('~','')
                                    val = parts[name2]
                                    word2 += val[::-1] if is_reversed2 else val
                            except KeyError:
                                st.error(f"Internal error: Variable '{name2}' not found in decomposed parts during word2 construction.")
                                continue

                            if word2 in self.words_set:

                                decomp_tuple = tuple(sorted(parts.items()))
                                if word1 == word2 and decomp_tuple in found_decompositions:
                                    continue

                                results_paired.append( (word1, word2, parts) )
                                found_decompositions.add(decomp_tuple)

                       handled = True


             if not handled:

                  st.warning(f"Equation solver currently supports simple variable checks (e.g., 'A'), reverse checks ('A;~A'), or sequence reversals ('ABC;CBA'). The pattern pair '{p1_str};{p2_str}' is not recognized or supported in this optimized mode.")
                  return []

        elif len(patterns) > 2:
            st.warning(f"Equation solver currently only supports 1 or 2 patterns after variable definitions (e.g., 'A', or 'A;~A', or 'ABC;CBA'). Queries with more patterns like '{';'.join(patterns)}' are not yet fully supported by the optimized solver.")
            return []


        return results_paired
    def execute_query(self, query):
        self.start_time = time.time()
        self._regex_cache = {}
        raw_parts = query.strip().split(';')
        parts = [p.strip() for p in raw_parts if p.strip()]

        variable_defs_raw = []
        search_patterns_raw = []
        variables = {}

        for part in parts:
            if '=' in part and part[0].isalpha() and part[0].isupper() and part[0] <= 'R':
                  variable_defs_raw.append(part)
            else:
                  search_patterns_raw.append(part)
        for v_def_str in variable_defs_raw:
            self._time_check()
            parsed_var = self.parse_variable_definition(v_def_str)
            if parsed_var:
                 variables[parsed_var['var_name']] = parsed_var
            else:
                 st.warning(f"Skipping invalid variable definition: {v_def_str}")

        is_equation_query = bool(variables) and bool(search_patterns_raw)
        is_anagram_query = any(p.startswith('/') for p in search_patterns_raw)

        results = []
        result_type = "simple"

        try:
            if is_equation_query:
                 result_type = "equation"
                 results = self.solve_equation(variables, search_patterns_raw)

            elif len(search_patterns_raw) == 1:
                 pattern = search_patterns_raw[0]
                 if pattern.startswith('/'):
                      result_type = "anagram"
                      matches = self.process_anagram_pattern(pattern)
                      results = [(m, None, {}) for m in matches]
                 else:
                      result_type = "simple"
                      matches = self.find_matches_simple_pattern(pattern)
                      results = [(m, None, {}) for m in matches]

            elif len(search_patterns_raw) > 1:

                  st.warning("Handling multiple non-equation patterns via intersection. Qat behavior might differ, especially with multiple anagrams.")
                  result_type = "intersection"
                  common_matches = None

                  for i, pattern in enumerate(search_patterns_raw):
                      self._time_check()
                      current_matches = set()
                      if pattern.startswith('/'):
                           matches_list = self.process_anagram_pattern(pattern)
                           if matches_list is not None: current_matches = set(matches_list)
                      else:
                           matches_list = self.find_matches_simple_pattern(pattern)
                           current_matches = set(matches_list)

                      if i == 0:
                           common_matches = current_matches
                      else:
                           common_matches &= current_matches

                      if not common_matches: break

                  if common_matches is not None:
                      results = [(m, None, {}) for m in sorted(list(common_matches))]


            else:
                 result_type = "definition_only"
                 st.info("Query contains only variable definitions. To see matching words, add the variable name(s) as patterns (e.g., A; B;).")
                 results = []


        except TimeoutError:
             st.error(f"Query timed out after {self.timeout} seconds.")
             return None, "timeout"
        except Exception as e:
             st.error(f"An error occurred during query execution: {e}")
             import traceback
             st.error(traceback.format_exc())
             return [], "error"


        return results, result_type


def format_results(results, result_type, max_disp):
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
             decomp_parts = [f"{decomp[key]}" for key in sorted(decomp.keys())]
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
                 timeout=timeout_seconds
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