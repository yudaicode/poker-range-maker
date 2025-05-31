import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import glob
from collections import Counter, defaultdict

# utils_judge.py と range_analyzer.py (の解析部分) から必要な関数をインポート
# これらは同じディレクトリにあるか、Pythonのパスが通っている必要がある
from utils_judge import (
    determine_position,
    extract_hero_cards,
    check_bb_defense,
    extract_preflop_actions,
    get_first_raise_info,
    normalize_hole_cards,
    had_opportunity_to_open
)
# range_analyzer.py から解析ロジックを移植またはインポートする必要がある
# ここでは、主要な解析関数を直接 gui_analyzer.py に含めるか、
# range_analyzer.py をリファクタリングしてインポート可能にすることを想定

# --- range_analyzer.py から持ってくる解析関連の関数 ---
# (実際には range_analyzer.py をリファクタリングしてインポートするのが望ましい)

def detect_hero_from_files_for_gui(history_dir):
    # (range_analyzer.py の detect_hero_from_files と同様のロジック)
    # GUI用に少し調整（printを避けるなど）
    import re
    player_counts = Counter()
    dealt_to_regex = re.compile(r"Dealt to (.+?) \[(?:..).?\]")
    found_files = False
    for filepath in glob.glob(os.path.join(history_dir, "*.txt")):
        found_files = True
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            for line in content.splitlines():
                match = dealt_to_regex.search(line)
                if match:
                    player_name = match.group(1).strip()
                    if player_name.endswith(" (observer)"):
                        player_name = player_name[:-11].strip()
                    if player_name:
                        player_counts[player_name] += 1
        except Exception:
            pass # GUIではエラーはmessageboxなどで表示する方が良い
    
    if not found_files: return None # ファイルが見つからなかった場合
    if not player_counts: return None

    sorted_players = player_counts.most_common()
    if not sorted_players: return None
    
    most_common_name, _ = sorted_players[0]
    if most_common_name.upper() == "HERO": # "HERO" (大文字・小文字問わず) が最も一般的であれば、それを優先
        for name, _ in sorted_players:
            if name.upper() == "HERO":
                return name
    return most_common_name


def parse_hand_history_file_for_gui(filepath, hero_name):
    # (range_analyzer.py の parse_hand_history_file と同様のロジック)
    # GUI用に調整
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return #ジェネレータなのでエラー時はここで終了

    primary_delimiter = None
    if "PokerStars Zoom Hand #" in content:
        primary_delimiter = "PokerStars Zoom Hand #"
    elif "PokerStars Hand #" in content:
        primary_delimiter = "PokerStars Hand #"
    elif "Poker Hand #" in content:
        primary_delimiter = "Poker Hand #"

    hand_texts_to_process = []
    if primary_delimiter:
        segments = content.split(primary_delimiter)
        for i in range(1, len(segments)):
            segment_content = segments[i]
            if segment_content.strip():
                hand_texts_to_process.append(primary_delimiter + segment_content)
    elif content.strip():
        hand_texts_to_process.append(content)
    
    if not hand_texts_to_process:
        return

    for current_hand_text in hand_texts_to_process:
        hero_cards_raw = extract_hero_cards(current_hand_text.splitlines(), hero_name)
        if not hero_cards_raw: continue
        normalized_hand = normalize_hole_cards(hero_cards_raw)
        if not normalized_hand: continue
        hero_position = determine_position(hero_name, current_hand_text)
        if hero_position == "Other": continue

        lines = current_hand_text.splitlines()
        preflop_lines = []
        preflop_started = False
        for line in lines:
            if "*** HOLE CARDS ***" in line: preflop_started = True; continue
            if "*** FLOP ***" in line or "*** SUMMARY ***" in line or "*** TURN ***" in line or "*** RIVER ***" in line: break
            if preflop_started and line.strip(): preflop_lines.append(line)
        
        if not preflop_lines: continue
        preflop_actions = extract_preflop_actions(preflop_lines)
        if not preflop_actions: continue

        is_hero_opener = False
        first_raiser, _, is_open_raise = get_first_raise_info(preflop_actions)
        if first_raiser == hero_name and is_open_raise: is_hero_opener = True

        hero_had_open_opportunity_flag = had_opportunity_to_open(preflop_actions, hero_name)
        hero_action_in_open_spot = None
        if hero_had_open_opportunity_flag:
            for player, action_type_spot in preflop_actions:
                if player == hero_name: hero_action_in_open_spot = action_type_spot; break
        
        # Modified BB defense logic
        bb_defense_action_type = None
        vs_position_bb = None
        if hero_position == "BB":
            # Check for an open raise by someone other than the hero
            if first_raiser and is_open_raise and first_raiser != hero_name:
                # check_bb_defense now returns (action_type, opponent_pos)
                # action_type can be "call", "raise", "fold", or None
                bb_defense_action_type, vs_position_bb_temp = check_bb_defense(current_hand_text, hero_name)
                if vs_position_bb_temp: # Ensure opponent position was determined
                    vs_position_bb = vs_position_bb_temp
                # If check_bb_defense returned (None, some_pos) or (None, None), 
                # bb_defense_action_type will be None. This case should ideally be handled
                # by earlier returns in check_bb_defense if no open raise or hero not BB.
                # If it's "fold", that's a valid action type.
        
        yield {
            "hand": normalized_hand, "position": hero_position,
            "is_hero_opener": is_hero_opener,
            "had_open_opportunity": hero_had_open_opportunity_flag,
            "hero_action_in_open_spot": hero_action_in_open_spot,
            # Replace old flags with new specific action
            "bb_defense_action": bb_defense_action_type, # "call", "raise", "fold", or None
            "vs_position_bb": vs_position_bb,
            # Add preflop_actions for 3bet analysis in analyze_data
            "preflop_actions": preflop_actions,
            "hand_history_text": current_hand_text,
        }

# --- GUI アプリケーションクラス ---
class PokerRangeGUI:
    def __init__(self, master):
        self.master = master
        master.title("Poker Hand Range Analyzer")
        master.geometry("800x600")

        self.data = {} # 解析結果を保持

        # --- 入力フレーム ---
        input_frame = ttk.LabelFrame(master, text="Input")
        input_frame.pack(padx=10, pady=10, fill="x")

        ttk.Label(input_frame, text="Hand History Directory:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.dir_entry_var = tk.StringVar()
        self.dir_entry = ttk.Entry(input_frame, textvariable=self.dir_entry_var, width=50)
        self.dir_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(input_frame, text="Select Folder", command=self.select_directory).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(input_frame, text="Hero Name:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.hero_name_var = tk.StringVar()
        self.hero_name_entry = ttk.Entry(input_frame, textvariable=self.hero_name_var, width=30)
        self.hero_name_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        # 自動検出ボタンは後で追加も検討

        self.analyze_button = ttk.Button(input_frame, text="Analyze Hands", command=self.analyze_data)
        self.analyze_button.grid(row=2, column=0, columnspan=3, padx=5, pady=10)
        
        input_frame.columnconfigure(1, weight=1) # Directory entry expands

        # --- 結果フィルタリングフレーム ---
        filter_frame = ttk.LabelFrame(master, text="Display Options")
        filter_frame.pack(padx=10, pady=(0,5), fill="x")

        ttk.Label(filter_frame, text="Action Type:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.action_type_var = tk.StringVar()
        self.action_type_combo = ttk.Combobox(filter_frame, textvariable=self.action_type_var, 
                                              values=["Open", "BB Defense", "3bet"], state="readonly")
        self.action_type_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.action_type_combo.bind("<<ComboboxSelected>>", self.on_filter_change)

        ttk.Label(filter_frame, text="Position:").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.position_var = tk.StringVar()
        self.position_combo = ttk.Combobox(filter_frame, textvariable=self.position_var, state="readonly")
        self.position_combo.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        self.position_combo.bind("<<ComboboxSelected>>", self.on_filter_change)
        
        # --- 結果表示エリア (タブ) ---
        self.notebook = ttk.Notebook(master)
        self.notebook.pack(padx=10, pady=10, expand=True, fill="both")
        
        # 初期メッセージ用タブ
        self.initial_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.initial_tab, text="Welcome")
        ttk.Label(self.initial_tab, text="Please select a directory and hero name, then click 'Analyze Hands'.").pack(padx=20, pady=20)
        
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(master, textvariable=self.status_var)
        self.status_label.pack(side="bottom", fill="x", padx=10, pady=5)
        self.status_var.set("Ready.")

        # Initialize selectors
        self._update_position_selector() # Call once to populate position_combo initially if needed
        self.action_type_combo.set("Open") # Default selection
        self.on_filter_change(None) # Trigger initial population of position selector based on default action

    def on_filter_change(self, event): # event is passed by a binding, can be None if called manually
        self._update_position_selector()
        # If data is already analyzed, refresh the displayed tabs
        if self.data:
            self.display_results_in_gui()

    def _update_position_selector(self):
        action = self.action_type_var.get()
        if action == "Open":
            self.position_combo['values'] = ["UTG", "HJ", "CO", "BTN", "SB", "ALL"]
            if not self.position_var.get() in self.position_combo['values']:
                 self.position_combo.set("ALL") # Default for Open
        elif action == "BB Defense":
            self.position_combo['values'] = ["UTG", "HJ", "CO", "BTN", "SB", "ALL"]
            if not self.position_var.get() in self.position_combo['values']:
                 self.position_combo.set("ALL") # Default for BB Defense
        elif action == "3bet":
            self.position_combo['values'] = ["UTG", "HJ", "CO", "BTN", "SB", "BB", "ALL"]
            if not self.position_var.get() in self.position_combo['values']:
                 self.position_combo.set("ALL") # Default for 3bet
        else:
            self.position_combo['values'] = [] # Should not happen if only Open is available
            self.position_combo.set("")

    def select_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.dir_entry_var.set(directory)
            self.status_var.set(f"Directory selected: {directory}")
            # 自動ヒーロー名検出
            detected_hero = detect_hero_from_files_for_gui(directory)
            if detected_hero:
                self.hero_name_var.set(detected_hero)
                self.status_var.set(f"Directory: {directory} | Detected Hero: {detected_hero}")
            else:
                self.status_var.set(f"Directory: {directory} | Could not auto-detect hero.")


    def analyze_data(self):
        history_dir = self.dir_entry_var.get()
        hero_name = self.hero_name_var.get()

        if not history_dir or not os.path.isdir(history_dir):
            messagebox.showerror("Error", "Please select a valid hand history directory.")
            return
        if not hero_name:
            messagebox.showerror("Error", "Please enter a hero name.")
            return

        self.status_var.set("Analyzing...")
        self.master.update_idletasks() # UIを更新

        # データ構造の初期化
        open_ranges = defaultdict(Counter)
        open_opportunity_all_hands_ranges = defaultdict(Counter)
        
        bb_call_defense_ranges = defaultdict(Counter) # BB Call defense
        bb_raise_defense_ranges = defaultdict(Counter) # BB Raise defense
        bb_defense_opportunity_fold_ranges = defaultdict(Counter)
        bb_defense_opportunity_all_hands_ranges = defaultdict(Counter)
        open_spot_fold_ranges = defaultdict(Counter) # Hero folded in an open spot
        open_spot_limp_ranges = defaultdict(Counter) # Hero limped (called) in an open spot
        
        threebet_ranges = defaultdict(Counter) # 3bet hands by hero position
        threebet_opportunity_all_hands_ranges = defaultdict(Counter) # All hands where hero had 3bet opportunity by position
        coldcall_ranges = defaultdict(Counter) # Cold call hands by hero position (in 3bet spot)
        threebet_fold_ranges = defaultdict(Counter) # Fold hands by hero position (in 3bet spot)

        # For vs-position breakdown
        threebet_ranges_by_vspos = defaultdict(lambda: defaultdict(Counter))
        coldcall_ranges_by_vspos = defaultdict(lambda: defaultdict(Counter))
        threebet_fold_ranges_by_vspos = defaultdict(lambda: defaultdict(Counter))
        threebet_opp_by_vspos = defaultdict(lambda: defaultdict(Counter))

        file_count = 0
        hand_count = 0

        for filepath in glob.glob(os.path.join(history_dir, "*.txt")):
            file_count += 1
            for parsed_hand in parse_hand_history_file_for_gui(filepath, hero_name):
                hand_count += 1
                hand = parsed_hand["hand"]
                position = parsed_hand["position"]
                current_hand_text = parsed_hand.get("hand_history_text", None)

                # Open Range
                if parsed_hand["had_open_opportunity"] and position != "BB": # BB can't open raise usually
                    open_opportunity_all_hands_ranges[position][hand] += 1
                    if parsed_hand["is_hero_opener"]:
                        open_ranges[position][hand] += 1
                    elif parsed_hand["hero_action_in_open_spot"] == 'fold':
                        open_spot_fold_ranges[position][hand] += 1
                    elif parsed_hand["hero_action_in_open_spot"] == 'call': # Limp
                        open_spot_limp_ranges[position][hand] += 1
                
                # BB Defense
                if position == "BB":
                    vs_pos = parsed_hand["vs_position_bb"]
                    action = parsed_hand["bb_defense_action"] # "call", "raise", "fold", or None
                    
                    if vs_pos and action: # Opportunity was there, and an action (call, raise, fold) was recorded
                        bb_defense_opportunity_all_hands_ranges[vs_pos][hand] += 1
                        if action == "call":
                            bb_call_defense_ranges[vs_pos][hand] += 1
                        elif action == "raise":
                            bb_raise_defense_ranges[vs_pos][hand] += 1
                        elif action == "fold":
                            bb_defense_opportunity_fold_ranges[vs_pos][hand] += 1
                    # If action is None but vs_pos exists, it implies an opportunity but no explicit hero action found
                    # This case might need review depending on how check_bb_defense behaves with missed actions.
                    # For now, it's counted in opportunity_all if vs_pos is valid.

                # 3bet Range
                # 3bet opportunity: hero's first action is a raise, but not the first raise in the hand (i.e., not open)
                # We count all hands where hero had a chance to 3bet (i.e., after a raise, before hero acts)
                # and what hands hero actually 3bet by position
                # We'll use preflop_actions and hero's position
                # Find all raises before hero acts
                preflop_actions = parsed_hand.get("preflop_actions", [])
                hero_first_action_idx = -1
                for i, (player, action) in enumerate(preflop_actions):
                    if player == hero_name:
                        hero_first_action_idx = i
                        break
                if hero_first_action_idx > 0:
                    # There is at least one action before hero acts
                    prior_raises = [j for j in range(hero_first_action_idx) if preflop_actions[j][1] == 'raise']
                    if prior_raises:
                        # There was a raise before hero acted (i.e., 3bet spot)
                        threebet_opportunity_all_hands_ranges[position][hand] += 1
                        if preflop_actions[hero_first_action_idx][1] == 'raise':
                            threebet_ranges[position][hand] += 1
                        elif preflop_actions[hero_first_action_idx][1] == 'call':
                            coldcall_ranges[position][hand] += 1
                        elif preflop_actions[hero_first_action_idx][1] == 'fold':
                            threebet_fold_ranges[position][hand] += 1

                        # vs-position breakdown
                        # Find the last raise before hero acts
                        last_raiser_idx = max(prior_raises)
                        last_raiser_name = preflop_actions[last_raiser_idx][0]
                        vs_pos = determine_position(last_raiser_name, current_hand_text) if last_raiser_name != hero_name else None
                        if vs_pos and vs_pos != 'Other':
                            threebet_opp_by_vspos[position][vs_pos][hand] += 1
                            if preflop_actions[hero_first_action_idx][1] == 'raise':
                                threebet_ranges_by_vspos[position][vs_pos][hand] += 1
                            elif preflop_actions[hero_first_action_idx][1] == 'call':
                                coldcall_ranges_by_vspos[position][vs_pos][hand] += 1
                            elif preflop_actions[hero_first_action_idx][1] == 'fold':
                                threebet_fold_ranges_by_vspos[position][vs_pos][hand] += 1

        self.data = {
            'open_ranges': open_ranges,
            'open_opportunity_all_hands_ranges': open_opportunity_all_hands_ranges,
            'bb_call_defense_ranges': bb_call_defense_ranges,
            'bb_raise_defense_ranges': bb_raise_defense_ranges,
            'bb_defense_opportunity_fold_ranges': bb_defense_opportunity_fold_ranges,
            'bb_defense_opportunity_all_hands_ranges': bb_defense_opportunity_all_hands_ranges,
            'open_spot_fold_ranges': open_spot_fold_ranges,
            'open_spot_limp_ranges': open_spot_limp_ranges,
            'threebet_ranges': threebet_ranges,
            'threebet_opportunity_all_hands_ranges': threebet_opportunity_all_hands_ranges,
            'coldcall_ranges': coldcall_ranges,
            'threebet_fold_ranges': threebet_fold_ranges,
            'threebet_ranges_by_vspos': threebet_ranges_by_vspos,
            'coldcall_ranges_by_vspos': coldcall_ranges_by_vspos,
            'threebet_fold_ranges_by_vspos': threebet_fold_ranges_by_vspos,
            'threebet_opp_by_vspos': threebet_opp_by_vspos,
        }
        
        if hand_count == 0:
            self.status_var.set(f"Analyzed {file_count} files. No hands found for hero '{hero_name}'.")
            messagebox.showinfo("Analysis Complete", f"Analyzed {file_count} files. No hands found for hero '{hero_name}'.")
        else:
            self.status_var.set(f"Analysis complete: {hand_count} hands from {file_count} files.")
            messagebox.showinfo("Analysis Complete", f"Analyzed {hand_count} hands from {file_count} files.")

        # Set default filters and display results
        self.action_type_combo.set("Open") 
        self._update_position_selector() # Update positions based on "Open"
        self.position_combo.set("ALL") # Default to "ALL" for the selected action type
        self.display_results_in_gui()


    def display_results_in_gui(self):
        # 既存のデータタブをクリア (Welcomeタブ以外)
        for i in reversed(range(self.notebook.index('end'))):
            tab_text = self.notebook.tab(i, "text")
            if tab_text != "Welcome":
                self.notebook.forget(i)

        if not self.data:
            self.status_var.set("No data to display. Analyze hands first.")
            if self.notebook.index('end') == 0: # Only welcome tab exists or no tabs
                 self.notebook.select(self.initial_tab)
            return

        action_filter = self.action_type_var.get()
        position_filter = self.position_var.get()
        
        tabs_created = 0
        first_tab_to_select = None

        positions_to_iterate = ["UTG", "HJ", "CO", "BTN", "SB"] # BB is not an opening position
        opponent_positions_bb = ["UTG", "HJ", "CO", "BTN", "SB"] # For BB defense
        positions_for_3bet = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]

        if action_filter == "Open":
            relevant_positions = [position_filter] if position_filter != "ALL" else positions_to_iterate
            for pos in relevant_positions:
                if pos in self.data['open_opportunity_all_hands_ranges'] or pos in self.data['open_ranges']:
                    # Open Freq %
                    tab = self.create_matrix_tab(
                        title=f"{pos} Raise Freq %",
                        opportunity_counter=self.data['open_opportunity_all_hands_ranges'].get(pos, Counter()),
                        action_counters={ 
                            'raise': self.data['open_ranges'].get(pos, Counter()),
                            'limp': self.data['open_spot_limp_ranges'].get(pos, Counter()),
                            'fold': self.data['open_spot_fold_ranges'].get(pos, Counter())
                        },
                        display_mode="open_freq"
                    )
                    if tab and not first_tab_to_select: first_tab_to_select = tab
                    tabs_created += 1
                    
                    # Open Opp ALL (Counts)
                    tab = self.create_matrix_tab(
                        title=f"{pos} Raise Opp. ALL (Counts)",
                        action_counters={'main': self.data['open_opportunity_all_hands_ranges'].get(pos, Counter())},
                        display_mode="count"
                    )
                    if tab and not first_tab_to_select: first_tab_to_select = tab
                    tabs_created += 1

                    # Actual Open (Counts) - This is just the raise counts
                    tab = self.create_matrix_tab(
                        title=f"{pos} Raise Actual (Counts)",
                        action_counters={'main': self.data['open_ranges'].get(pos, Counter())},
                        display_mode="count"
                    )
                    if tab and not first_tab_to_select: first_tab_to_select = tab
                    tabs_created += 1

        elif action_filter == "BB Defense":
            relevant_vs_positions = [position_filter] if position_filter != "ALL" else opponent_positions_bb
            for vs_pos in relevant_vs_positions:
                has_data_for_vs_pos = (
                    vs_pos in self.data['bb_defense_opportunity_all_hands_ranges'] or
                    vs_pos in self.data['bb_call_defense_ranges'] or
                    vs_pos in self.data['bb_raise_defense_ranges'] or
                    vs_pos in self.data['bb_defense_opportunity_fold_ranges']
                )
                if has_data_for_vs_pos:
                    # Combined BB Defense Freq % (Call + Raise + Fold)
                    tab = self.create_matrix_tab(
                        title=f"BB Def Freq (vs {vs_pos})",
                        opportunity_counter=self.data['bb_defense_opportunity_all_hands_ranges'].get(vs_pos, Counter()),
                        action_counters={ # For bb_defense_freq mode
                            'call': self.data['bb_call_defense_ranges'].get(vs_pos, Counter()),
                            'raise': self.data['bb_raise_defense_ranges'].get(vs_pos, Counter()),
                            'fold': self.data['bb_defense_opportunity_fold_ranges'].get(vs_pos, Counter())
                        },
                        display_mode="bb_defense_freq"
                    )
                    if tab and not first_tab_to_select: first_tab_to_select = tab
                    tabs_created += 1

                    # BB Def Opp ALL (Counts)
                    tab = self.create_matrix_tab(
                        title=f"BB Def Opp ALL (Counts vs {vs_pos})",
                        action_counters={'main': self.data['bb_defense_opportunity_all_hands_ranges'].get(vs_pos, Counter())},
                        display_mode="count"
                    )
                    if tab and not first_tab_to_select: first_tab_to_select = tab
                    tabs_created += 1
                    
                    # BB Def Actual (Counts - Call + Raise)
                    combined_bb_def_actual = Counter(self.data['bb_call_defense_ranges'].get(vs_pos, Counter()))
                    combined_bb_def_actual.update(self.data['bb_raise_defense_ranges'].get(vs_pos, Counter()))
                    tab = self.create_matrix_tab(
                        title=f"BB Def Actual (Counts vs {vs_pos})",
                        action_counters={'main': combined_bb_def_actual},
                        display_mode="count"
                    )
                    if tab and not first_tab_to_select: first_tab_to_select = tab
                    tabs_created += 1

                    # BB Fold (Counts)
                    tab = self.create_matrix_tab(
                        title=f"BB Fold (Counts vs {vs_pos})",
                        action_counters={'main': self.data['bb_defense_opportunity_fold_ranges'].get(vs_pos, Counter())},
                        display_mode="count"
                    )
                    if tab and not first_tab_to_select: first_tab_to_select = tab
                    tabs_created += 1
        
        elif action_filter == "3bet":
            relevant_positions = [position_filter] if position_filter != "ALL" else positions_for_3bet
            for pos in relevant_positions:
                # vs-position breakdown
                vspos_dict = self.data['threebet_opp_by_vspos'].get(pos, {})
                if vspos_dict:
                    for vs_pos in [p for p in positions_for_3bet if p != pos]:
                        opp_counter = self.data['threebet_opp_by_vspos'][pos].get(vs_pos, Counter())
                        if not opp_counter:
                            continue
                        tab = self.create_matrix_tab(
                            title=f"{pos} vs {vs_pos} 3bet spot Freq %",
                            opportunity_counter=opp_counter,
                            action_counters={
                                'raise': self.data['threebet_ranges_by_vspos'][pos][vs_pos],
                                'call': self.data['coldcall_ranges_by_vspos'][pos][vs_pos],
                                'fold': self.data['threebet_fold_ranges_by_vspos'][pos][vs_pos],
                            },
                            display_mode="threeway_freq"
                        )
                        if tab and not first_tab_to_select: first_tab_to_select = tab
                        tabs_created += 1
                        # Opp count
                        tab = self.create_matrix_tab(
                            title=f"{pos} vs {vs_pos} Opp count",
                            action_counters={'main': opp_counter},
                            display_mode="count"
                        )
                        if tab and not first_tab_to_select: first_tab_to_select = tab
                        tabs_created += 1
                        # 3bet Actual count
                        tab = self.create_matrix_tab(
                            title=f"{pos} vs {vs_pos} 3bet Actual count",
                            action_counters={'main': self.data['threebet_ranges_by_vspos'][pos][vs_pos]},
                            display_mode="count"
                        )
                        if tab and not first_tab_to_select: first_tab_to_select = tab
                        tabs_created += 1
                        # cold call Actual count
                        tab = self.create_matrix_tab(
                            title=f"{pos} vs {vs_pos} cold call Actual count",
                            action_counters={'main': self.data['coldcall_ranges_by_vspos'][pos][vs_pos]},
                            display_mode="count"
                        )
                        if tab and not first_tab_to_select: first_tab_to_select = tab
                        tabs_created += 1
                        # fold Actual count
                        tab = self.create_matrix_tab(
                            title=f"{pos} vs {vs_pos} fold Actual count",
                            action_counters={'main': self.data['threebet_fold_ranges_by_vspos'][pos][vs_pos]},
                            display_mode="count"
                        )
                        if tab and not first_tab_to_select: first_tab_to_select = tab
                        tabs_created += 1
                # fallback: if no vspos breakdown, show overall
                elif pos in self.data['threebet_opportunity_all_hands_ranges'] or pos in self.data['threebet_ranges']:
                    tab = self.create_matrix_tab(
                        title=f"{pos} 3bet spot Freq %",
                        opportunity_counter=self.data['threebet_opportunity_all_hands_ranges'].get(pos, Counter()),
                        action_counters={
                            'raise': self.data['threebet_ranges'].get(pos, Counter()),
                            'call': self.data['coldcall_ranges'].get(pos, Counter()),
                            'fold': self.data['threebet_fold_ranges'].get(pos, Counter()),
                        },
                        display_mode="threeway_freq"
                    )
                    if tab and not first_tab_to_select: first_tab_to_select = tab
                    tabs_created += 1

        if tabs_created == 0:
            self.status_var.set(f"No data for current filter: {action_filter} / {position_filter}. Select other options or analyze data.")
            # Welcomeタブがなければ表示 (通常はあるはず)
            if self.notebook.index('end') == 0 : # no tabs at all
                 self.notebook.select(self.initial_tab)
            elif self.notebook.tab(0, "text") == "Welcome": # if welcome is the only tab.
                 self.notebook.select(0)

        elif first_tab_to_select:
            self.notebook.select(first_tab_to_select)
            self.status_var.set(f"Displaying: {action_filter} / {position_filter}")
        
        if self.notebook.index('end') > 0 and self.notebook.tab(0, "text") == "Welcome" and tabs_created > 0 :
             self.notebook.hide(self.initial_tab) # Hide welcome tab if other tabs are present
        elif tabs_created == 0 and self.notebook.index('end') > 0 and self.notebook.tab(0, "text") == "Welcome":
             self.notebook.add(self.initial_tab) # Ensure welcome tab is visible if no data tabs
             self.notebook.select(self.initial_tab)


    def _redraw_canvas_cell(self, event, canvas_widget, freq1, freq2, freq3, cell_text, mode):
        canvas_widget.delete("all")
        width = canvas_widget.winfo_width()
        height = canvas_widget.winfo_height()

        if width <= 1 or height <= 1: # Not visible or too small
            return

        bg_color = '#F0F0F0' 
        text_color = "black" 
        total_colored_freq = 0.0
        current_x = 0

        if mode == "open_freq":
            open_raise_freq = freq1 # Raise, Red
            open_limp_freq = freq2  # Limp, Grey (this was previously fold freq, now limp freq)
            open_fold_freq = freq3  # Fold, Blue (this was previously not used by open_freq, now fold freq)
            
            # 1. Draw open raise portion (#FF0058 Red)
            bar_raise_width = width * open_raise_freq
            if bar_raise_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_raise_width, height, fill="#FF0058", outline="") 
            current_x += bar_raise_width

            # 2. Draw open limp portion (New: Yellow)
            bar_limp_width = width * open_limp_freq
            if bar_limp_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_limp_width, height, fill="#FFFF99", outline="") # Light Yellow
            current_x += bar_limp_width
            
            # 3. Draw open fold portion (#0A92CF Blue)
            bar_fold_width = width * open_fold_freq
            if bar_fold_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_fold_width, height, fill="#0A92CF", outline="") 
            # current_x += bar_fold_width # Last bar
            
            total_colored_freq = open_raise_freq + open_limp_freq + open_fold_freq
            if total_colored_freq < 1.0:
                 canvas_widget.create_rectangle(width * total_colored_freq, 0, width, height, fill=bg_color, outline="")

        elif mode == "bb_defense_freq":
            # freq1 is Call Freq, freq2 is Raise Freq, freq3 is Fold Freq from create_matrix_tab
            raise_action_freq = freq2 
            call_action_freq = freq1  
            fold_action_freq = freq3  
            
            current_x = 0
            # 1. Draw Raise portion (Red)
            bar_raise_width = width * raise_action_freq
            if bar_raise_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_raise_width, height, fill="#FF0058", outline="") 
            current_x += bar_raise_width

            # 2. Draw Call portion (Green)
            bar_call_width = width * call_action_freq
            if bar_call_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_call_width, height, fill="#62E45A", outline="") 
            current_x += bar_call_width

            # 3. Draw Fold portion (Blue)
            bar_fold_width = width * fold_action_freq
            if bar_fold_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_fold_width, height, fill="#0A92CF", outline="") 
            # current_x += bar_fold_width # Not needed if this is the last bar before background fill
            
            total_colored_freq = raise_action_freq + call_action_freq + fold_action_freq
            # Fill remaining with background
            if total_colored_freq < 1.0:
                 # The starting x for background fill should be the end of the last colored bar
                 canvas_widget.create_rectangle(width * total_colored_freq, 0, width, height, fill=bg_color, outline="")

        elif mode == "single_freq":
            bar_width = width * freq1
            if bar_width > 0:
                canvas_widget.create_rectangle(0, 0, bar_width, height, fill="#FF0058", outline="")
            if freq1 < 1.0:
                canvas_widget.create_rectangle(bar_width, 0, width, height, fill=bg_color, outline="")
        elif mode == "threeway_freq":
            # freq1: raise (red), freq2: call (green), freq3: fold (blue)
            bar_raise_width = width * freq1
            if bar_raise_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_raise_width, height, fill="#FF0058", outline="")
            current_x += bar_raise_width
            bar_call_width = width * freq2
            if bar_call_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_call_width, height, fill="#62E45A", outline="")
            current_x += bar_call_width
            bar_fold_width = width * freq3
            if bar_fold_width > 0:
                canvas_widget.create_rectangle(current_x, 0, current_x + bar_fold_width, height, fill="#0A92CF", outline="")
            total_colored_freq = freq1 + freq2 + freq3
            if total_colored_freq < 1.0:
                canvas_widget.create_rectangle(width * total_colored_freq, 0, width, height, fill=bg_color, outline="")
        else: # Count mode or unknown - just fill with background
            canvas_widget.create_rectangle(0, 0, width, height, fill=bg_color, outline="")

        # Text color decision - Always black
        text_color = "black"
        
        # Center text
        canvas_widget.create_text(width / 2, height / 2, text=cell_text, fill=text_color, anchor="center", justify="center")


    def create_matrix_tab(self, title, opportunity_counter=None, 
                          action_counters=None, # Expected to be a dict like {'main': Counter, 'second': Counter, 'third': Counter}
                          display_mode="count"):
        # display_mode: "count", "open_freq", "bb_defense_freq"
        
        tab_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(tab_frame, text=title)

        base_hands = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']

        # Configure grid weights for responsiveness for the tab_frame itself
        # Row 0 and Column 0 for headers, not weighted for resizing
        tab_frame.grid_rowconfigure(0, weight=0)
        tab_frame.grid_columnconfigure(0, weight=0)
        for i in range(len(base_hands)):
            # Cells (1-13) are weighted for resizing
            tab_frame.grid_columnconfigure(i + 1, weight=1, minsize=40) 
            tab_frame.grid_rowconfigure(i + 1, weight=1, minsize=30)    

        # Add column headers (A-2)
        for i, rank_char in enumerate(base_hands):
            header_label = ttk.Label(tab_frame, text=rank_char, relief="solid", borderwidth=1, anchor="center")
            header_label.grid(row=0, column=i + 1, sticky="nsew")

        # Add row headers (A-2)
        for i, rank_char in enumerate(base_hands):
            header_label = ttk.Label(tab_frame, text=rank_char, relief="solid", borderwidth=1, anchor="center")
            header_label.grid(row=i + 1, column=0, sticky="nsew")

        for r, rank1 in enumerate(base_hands):
            for c, rank2 in enumerate(base_hands):
                is_pair = (rank1 == rank2)
                is_suited = (r < c)
                is_offsuit = (r > c)

                hand_str = ""
                if is_pair: hand_str = rank1 + rank2
                elif is_suited: hand_str = rank1 + rank2 + 's'
                else: hand_str = rank2 + rank1 + 'o'
                
                opp_value = opportunity_counter.get(hand_str, 0) if opportunity_counter else 0

                cell_canvas = tk.Canvas(tab_frame, bg='#F0F0F0', highlightthickness=1, highlightbackground="lightgrey")
                cell_canvas.grid(row=r + 1, column=c + 1, sticky="nsew") # Offset by 1 for headers

                text_to_display = ""
                freq1_for_draw, freq2_for_draw, freq3_for_draw = 0.0, 0.0, 0.0
                current_redraw_mode = "count" # default for actual counts or single_freq if not specified

                if display_mode == "open_freq":
                    current_redraw_mode = "open_freq"
                    open_raise_count = action_counters['raise'].get(hand_str, 0) if action_counters and 'raise' in action_counters else 0
                    open_limp_count = action_counters['limp'].get(hand_str, 0) if action_counters and 'limp' in action_counters else 0
                    open_fold_count = action_counters['fold'].get(hand_str, 0) if action_counters and 'fold' in action_counters else 0
                    
                    if opp_value > 0:
                        raise_freq_val = open_raise_count / opp_value 
                        limp_freq_val = open_limp_count / opp_value
                        fold_freq_val = open_fold_count / opp_value  
                        
                        freq1_for_draw = raise_freq_val
                        freq2_for_draw = limp_freq_val
                        freq3_for_draw = fold_freq_val

                        if raise_freq_val == 0 and limp_freq_val == 0 and fold_freq_val == 0:
                            text_to_display = "0%"
                        else:
                            text_to_display = f"R:{raise_freq_val:.0%}\nL:{limp_freq_val:.0%}\nF:{fold_freq_val:.0%}"
                    elif open_raise_count > 0 or open_limp_count > 0 or open_fold_count > 0:
                        text_to_display = "Err"
                        freq1_for_draw = 1.0 # Indicate error with full bar
                    else:
                        text_to_display = "N/A"

                elif display_mode == "bb_defense_freq":
                    current_redraw_mode = "bb_defense_freq"
                    call_count = action_counters['call'].get(hand_str, 0) if action_counters and 'call' in action_counters else 0
                    raise_count = action_counters['raise'].get(hand_str, 0) if action_counters and 'raise' in action_counters else 0
                    fold_count = action_counters['fold'].get(hand_str, 0) if action_counters and 'fold' in action_counters else 0
                    
                    if opp_value > 0:
                        call_freq_val = call_count / opp_value    # Corresponds to freq1_for_draw
                        raise_freq_val = raise_count / opp_value   # Corresponds to freq2_for_draw
                        fold_freq_val = fold_count / opp_value    # Corresponds to freq3_for_draw
                        
                        freq1_for_draw = call_freq_val
                        freq2_for_draw = raise_freq_val
                        freq3_for_draw = fold_freq_val

                        if call_freq_val == 0 and raise_freq_val == 0 and fold_freq_val == 0:
                            text_to_display = "0%"
                        else:
                            # Display order: Raise, Call, Fold
                            text_to_display = f"R:{raise_freq_val:.0%}\nC:{call_freq_val:.0%}\nF:{fold_freq_val:.0%}"
                    elif call_count > 0 or raise_count > 0 or fold_count > 0:
                        text_to_display = "Err"
                        freq1_for_draw = 1.0 # Indicate error
                    else:
                        text_to_display = "N/A"
                
                elif display_mode == "count":
                    current_redraw_mode = "count" # Explicitly set for clarity
                    count_val = action_counters['main'].get(hand_str, 0) if action_counters and 'main' in action_counters else 0
                    text_to_display = str(count_val)
                    # No frequencies to draw for count mode, bars will be empty by default in _redraw_canvas_cell if mode is count
                
                elif display_mode == "single_freq":
                    current_redraw_mode = "single_freq"
                    # For single_freq: action_counters['raise'] or ['call'] or ['fold'] is the actual count, opp_value is the opportunity count
                    # Use whichever key is present in action_counters
                    key = next(iter(action_counters.keys())) if action_counters else None
                    count = action_counters[key].get(hand_str, 0) if action_counters and key in action_counters else 0
                    if opp_value > 0:
                        freq = count / opp_value
                        freq1_for_draw = freq
                        if freq == 0:
                            text_to_display = "0%"
                        else:
                            text_to_display = f"{freq:.0%}"
                    elif count > 0:
                        text_to_display = "Err"
                        freq1_for_draw = 1.0
                    else:
                        text_to_display = "N/A"
                
                elif display_mode == "threeway_freq":
                    current_redraw_mode = "threeway_freq"
                    raise_count = action_counters['raise'].get(hand_str, 0) if action_counters and 'raise' in action_counters else 0
                    call_count = action_counters['call'].get(hand_str, 0) if action_counters and 'call' in action_counters else 0
                    fold_count = action_counters['fold'].get(hand_str, 0) if action_counters and 'fold' in action_counters else 0
                    if opp_value > 0:
                        raise_freq_val = raise_count / opp_value
                        call_freq_val = call_count / opp_value
                        fold_freq_val = fold_count / opp_value
                        freq1_for_draw = raise_freq_val
                        freq2_for_draw = call_freq_val
                        freq3_for_draw = fold_freq_val
                        if raise_freq_val == 0 and call_freq_val == 0 and fold_freq_val == 0:
                            text_to_display = "0%"
                        else:
                            text_to_display = f"R:{raise_freq_val:.0%}\nC:{call_freq_val:.0%}\nF:{fold_freq_val:.0%}"
                    elif raise_count > 0 or call_count > 0 or fold_count > 0:
                        text_to_display = "Err"
                        freq1_for_draw = 1.0
                    else:
                        text_to_display = "N/A"
                
                # Bind Configure
                cell_canvas.bind(
                    "<Configure>",
                    (lambda f1=freq1_for_draw, f2=freq2_for_draw, f3=freq3_for_draw, text=text_to_display, mode=current_redraw_mode, widget=cell_canvas:
                        lambda event: self._redraw_canvas_cell(event, widget, f1, f2, f3, text, mode)
                    )()
                )
        return tab_frame

def main_gui():
    root = tk.Tk()
    gui = PokerRangeGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main_gui()

# 注意: このファイルは utils_judge.py と同じディレクトリに置くか、
# utils_judge.py が含まれるディレクトリがPythonの検索パスに含まれている必要があります。
# また、range_analyzer.py から解析ロジックを適切に分離・インポートする構造が理想的です。
# この例では、簡単のため一部の解析関数を直接含めていますが、
# 本来は range_analyzer.py をリファクタリングして、
# `process_directory(history_dir, hero_name)` のような関数を呼び出し、
# 結果の辞書を受け取る形にするのがクリーンです。 