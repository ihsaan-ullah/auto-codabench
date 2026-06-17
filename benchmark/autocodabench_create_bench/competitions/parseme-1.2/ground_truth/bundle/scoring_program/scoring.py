# Imports
import json
import os
import sys
import evaluate
import subprocess
import re
from generate_files import Generate_files


# Paths
pred_dir = os.path.join('/app/input', 'res')
if not os.path.exists(pred_dir):
    print("ERROR: prediction directory does not exist")
    sys.exit(1)
ref_dir = os.path.join('/app/input', 'ref')
if not os.path.exists(ref_dir):
    print("ERROR: reference directory does not exist")
    sys.exit(1)
"""
input_dir = '/app/input_data/'
if not os.path.exists(input_dir):
    print("ERROR: input_data directory does not exist")
    sys.exit(1)"""
score_dir = '/app/output/'
if not os.path.exists(score_dir):
    print("ERROR: score directory does not exist")
    sys.exit(1)
program_dir = '/app/program/'
if not os.path.exists(program_dir):
    print("ERROR: program directory does not exist")
    sys.exit(1)


# Class
class Score:
    '''Class responsible for loading the scores of all the provided predictions and producing the scores.json and detailed_results.html files'''

    def __init__(self):
        '''Create the instance variables for the given inputed data'''
        self.langues = ['DE', 'EL', 'EU', 'FR', 'GA', 'HE', 'HI', 'IT', 'PL', 'PT', 'RO', 'SV', 'TR', 'ZH']
        self.scores = {}
        self.nbr_lang = len([value for value in self.langues if value in os.listdir(pred_dir)])
        if self.nbr_lang == 0:
            print("ERROR: No language file has been detected in your submission. Please check the structure of your submission!")
            sys.exit(1)
        self.lang_single = ['DE', 'FR', 'GA', 'HE', 'IT', 'SV', 'TR', 'ZH']
        self.nbr_lang_single = len([value for value in self.lang_single if value in os.listdir(pred_dir)])

    def load_scores(self):
        '''Load all the scores related to the inputed data inside the scores dictionnary'''
        evaluate_script = "evaluate.py"
        cptr = 1
        if not os.path.exists(evaluate_script):
            print("Error: evaluate script does not exist")
            sys.exit(1)
        for langue in self.langues:
            print("\rLanguage being processed: " + str(cptr) +"/" + str(len(self.langues)))
            cptr += 1
            lang_pred = os.path.join(pred_dir, langue, 'test.system.cupt')
            lang_gold = os.path.join(ref_dir, langue, 'test.cupt')
            lang_train = os.path.join(ref_dir, langue, 'train.cupt')
            lang_dev = os.path.join(ref_dir, langue, 'dev.cupt')
            if not os.path.exists(lang_gold):
                print("ERROR: reference file doesn't exist for " + langue + "; path = " + lang_gold)
                sys.exit(1)
            if not os.path.exists(lang_train):
                print("ERROR: training file doesn't exist for " + langue + "; path = " + lang_train)
                sys.exit(1)
            if not os.path.exists(lang_dev):
                print("ERROR: dev file doesn't exist for " + langue + "; path = " + lang_dev)
                sys.exit(1)
            self.scores[langue] = {}
            sub_dict = self.scores[langue]
            if not os.path.exists(lang_pred): # Load 0.0 to every position in scores for the language if the language file was not provided
                for category in ["Global", "Per-category", "Continuity", "Number-of-tokens", "Un-seen", "Variation"]:
                    sub_dict[category] = {}
                    if category == "Global":
                        for type_ in ["MWE-based", "Tok-based"]:
                            sub_dict[category][type_] = [0.0, 0.0, 0.0]
                    elif category == "Per-category":
                        test_stats_dir = os.path.join(ref_dir, langue, 'test-stats.md')
                        if not os.path.exists(test_stats_dir):
                            print("ERROR: statistics markdown file doesn't exist for " + langue)
                            sys.exit(1)
                        with open(test_stats_dir, 'r') as f:
                            for line in f:
                                _match = re.match(r"  \* \`(?P<type>[a-zA-Z\.]+)[0-9\`\:\n ]+", line)
                                if _match:
                                    if _match.group("type") not in sub_dict[category]:
                                        sub_dict[category][_match.group("type")] = {}
                                    for subtype in ["MWE-based", "Tok-based"]:
                                        sub_dict[category][_match.group("type")][subtype] = [0.0, 0.0, 0.0]
                    else:
                        for type_ in ["Continuous MWE-based", "Discontinuous MWE-based", "Multi-token MWE-based", "Single-token MWE-based", "Seen-in-traindev MWE-based", "Unseen-in-traindev MWE-based", "Variant-of-traindev MWE-based", "Identical-to-traindev MWE-based"]:
                            sub_dict[category][type_] = [0.0, 0.0, 0.0]
            else: # Calls the evaluate script to score the provided test.system.cupt for the language
                result = subprocess.run(['python3', evaluate_script, '--train', lang_train, '--dev', lang_dev, '--pred', lang_pred, '--gold', lang_gold], capture_output=True, text=True)
                content = result.stdout.split('\n')
                current_category = ""
                for line in content:
                    if line.startswith('#'):
                        p = re.compile(r"## (?P<category>[a-zA-Z\- ]+)[a-zA-Z\(\) ]*")
                        _match = p.match(line)
                        categ = _match.group("category")
                        if categ == "Global evaluation":
                            current_category = "Global"
                        elif categ == "Per-category evaluation ":
                            current_category = "Per-category"
                        elif categ == "MWE continuity ":
                            current_category = "Continuity"
                        elif categ == "Number of tokens ":
                            current_category = "Number-of-tokens"
                        elif categ == "Whether seen in train ":
                            current_category = "Un-seen"
                        elif categ == "Whether identical to train ":
                            current_category = "Variation"
                        else:
                            print("ERROR: category not recognized")
                            sys.exit(1)
                        sub_dict[current_category] = {}
                    elif line and current_category:
                        if ("MWE-based" in line) or ("Tok-based" in line):
                            p = re.compile(r"\* (?P<type>[a-zA-Z\-\.]+): ((?P<subtype>[a-zA-Z\-]+): )?P=[0-9\/]+=(?P<precision>[0-9\.]+) R=[0-9\/]+=(?P<recall>[0-9\.]+) F=(?P<f_score>[0-9\.]+)")
                            _match = p.match(line)
                            if current_category == "Global":
                                sub_dict[current_category][_match.group("type")] = [float(_match.group("precision"))*100, float(_match.group("recall"))*100, float(_match.group("f_score"))*100]
                            elif current_category == "Per-category":
                                if _match.group("type") not in sub_dict[current_category]:
                                    sub_dict[current_category][_match.group("type")] = {}
                                sub_dict[current_category][_match.group("type")][_match.group("subtype")] = [float(_match.group("precision"))*100, float(_match.group("recall"))*100, float(_match.group("f_score"))*100]
                            else:
                                sub_dict[current_category][_match.group("type") + ' ' + _match.group("subtype")] = [float(_match.group("precision"))*100, float(_match.group("recall"))*100, float(_match.group("f_score"))*100]



# Main
if __name__ == "__main__":
    score = Score()
    print("Loading scores")
    score.load_scores()
    print("Scores loaded successfuly")
    print("Generating output")
    gen = Generate_files(score.scores, score_dir, score.langues, score.lang_single, score.nbr_lang, score.nbr_lang_single)
    gen.generate_json()
    gen.generate_html()
    print("Output generated successfuly")
