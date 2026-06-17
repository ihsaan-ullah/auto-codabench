# Imports
import json
import os



# Class
class Generate_files:
	'''Class responsible for generating the scoring files, scores.json and detailed_results.html'''

	def __init__(self, scores, output_path, lang, lang_single, nbr_lang, nbr_lang_single):
		'''Load information retrieved by the Score class, general information and instance variables'''
		self.scores = scores
		self.output_path = output_path
		self.lang = lang
		self.lang_single = lang_single
		self.nbr_lang = nbr_lang
		self.nbr_lang_single = nbr_lang_single
		self.general = {}

	# Helper methods
	def _compute_average_P_R_F(self, PRF_list):
		'''Helper method used by generate_json and generate_html to compute the average P, R and F-score of macro-averages'''
		result = [round(sum(x)/len(x),2) for x in list(zip(*PRF_list))[:2]]
		if result[0]==0 and result[1]==0:
			result += [0]
			return result
		result += [(2*result[0]*result[1])/(result[0]+result[1])] # F-score formula recomputed from average P and R
		return result

	def _compute_macroavg(self, category, _type):
		'''Helper method used to compute the macro-averages for the specified category and type'''
		if _type == "Single-token MWE-based":
			temp_list = [self.scores[language][category][_type] for language in self.lang_single]
			return self._compute_average_P_R_F(temp_list)
		temp_list = [self.scores[language][category][_type] for language in self.lang]
		return self._compute_average_P_R_F(temp_list)

	def _html_macroavg(self, title, category):
		'''Helper method used to create html tables for cross-lingual macro-averages'''
		codex = {
			"General": ["Unseen MWE-based", "Global MWE-based", "Global Token-based"],
			"Continuity": ["Discontinuous MWE-based", "Continuous MWE-based"],
			"Un-seen": ["Unseen-in-traindev MWE-based", "Seen-in-traindev MWE-based"],
			"Variation": ["Variant-of-traindev MWE-based", "Identical-to-traindev MWE-based"],
			"Number-of-tokens": ["Single-token MWE-based", "Multi-token MWE-based"]
		}
		s = (
			'<h2>' + title + ':</h2>\n'
			'<table class="styled-table">\n'
			'<thead>\n'
			'\t<tr>\n'
		)
		if category == "General":
			s += '\t\t<th rowspan="2">#Langs</th>\n'
			for header in codex[category]:
				s += '\t\t<th colspan="3">' + header +'</th>\n'
			s += (
				'\t</tr>\n'
				'\t<tr>\n'
			)
			s += len(codex[category]) * (
				'\t\t<th>P</th>\n'
				'\t\t<th>R</th>\n'
				'\t\t<th>F</th>\n'
			)
		else:
			for header in codex[category]:
				s += '\t\t<th colspan="4">' + header +'</th>\n'
			s += (
				'\t</tr>\n'
				'\t<tr>\n'
			)
			s += len(codex[category]) * (
				'\t\t<th>#Langs</th>\n'
				'\t\t<th>P</th>\n'
				'\t\t<th>R</th>\n'
				'\t\t<th>F</th>\n'
			)
		s += (
		'\t</tr>\n'
		'</thead>\n'
		'<tbody>\n'
		'\t<tr>\n'
		)
       
		if category == "General":
			s += '\t\t<td>' + str(self.nbr_lang) + '/14</td>\n'
			for values in self.general.values():
				s += '\t\t<td>' + str(round(values, 2)) + '</td>\n'
			s += '\t</tr>\n'
		else:
			for _type in codex[category]:
				if _type == "Single-token MWE-based":
					s += '\t\t<td>' + str(self.nbr_lang_single) + '/' + str(len(self.lang_single)) +'</td>\n'
				else:
					s += '\t\t<td>' + str(self.nbr_lang) + '/14</td>\n'
				for values in self._compute_macroavg(category, _type):
					s += '\t\t<td>' + str(round(values, 2)) + '</td>\n'
			s += '\t</tr>\n'
		s += (
			'</tbody>\n'
			'</table>\n'
			'<br>\n'
		)
		return s

	# Main methods
	def generate_json(self):
		'''Generate the scores.json file to the specified output_path'''
		score_path = os.path.join(self.output_path, "scores.json")
		temp_list = [self.scores[language]["Un-seen"]["Unseen-in-traindev MWE-based"] for language in self.lang]
		general_unseen = self._compute_average_P_R_F(temp_list)
		temp_list = [self.scores[language]["Global"]["MWE-based"] for language in self.lang]
		general_mwe = self._compute_average_P_R_F(temp_list)
		temp_list = [self.scores[language]["Global"]["Tok-based"] for language in self.lang]
		general_tok = self._compute_average_P_R_F(temp_list)
		labels = [x + y for x in ["Unseen MWE-based ", "Global MWE-based ", "Global Token-based "] for y in ['P', 'R', 'F']]
		self.general = {label: value for label, value in zip(labels, general_unseen + general_mwe + general_tok)}

		with open(score_path, 'w') as score_file:
			score_file.write(json.dumps(self.general))

	def generate_html(self):
		'''Generate the detailed_results.html file to the specified output_path'''
		html_path = os.path.join(self.output_path, "detailed_results.html")
		result = (
			'<!DOCTYPE html>\n'
			'<html>\n'
			'<head>\n'
			'<style>\n'
			'.styled-table {\n'
			'\tborder-collapse: collapse;\n'
			'\tmargin: 14px 0;\n'
			'\tmargin-left: 60px;\n'
			'\tfont-size: 0.9em;\n'
			'\tfont-family: sans-serif;\n'
			'\tmin-width: 400px;\n'
			'\tbox-shadow: 0 0 20px rgba(0, 0, 0, 0.15);\n'
			'}\n'
			'.styled-table thead tr {\n'
			'\tbackground-color: #34495e;\n'
			'\tborder: 1px solid #ffffff;\n'
			'\tcolor: #ffffff;\n'
			'\ttext-align: center;\n'
			'}\n'
			'.styled-table th,\n'
			'.styled-table td {\n'
			'\tpadding: 12px 15px;\n'
			'\ttext-align: center;\n'
			'\tmin-width: 45px;\n'
			'}\n'
			'.styled-table tbody tr {\n'
			'\tborder-bottom: 1px solid #dddddd;\n'
			'}\n'
			'.styled-table tbody tr:nth-of-type(even) {\n'
			'\tbackground-color: #f3f3f3;\n'
			'}\n'
			'.styled-table tbody tr:last-of-type {\n'
			'\tborder-bottom: 2px solid #34495e;\n'
			'</style>\n'
			'</head>\n'
			'<body>\n'
			'<h1 style="color: steelblue;">Cross-lingual macro-averages</h2>\n'
			'<p style="line-height: 65%;"> <br> </p>\n'
		)

		# Macro-avg tables
		result += self._html_macroavg("General ranking", "General")
		result += self._html_macroavg("Discontinuous vs Continuous VMWEs", "Continuity")
		result += self._html_macroavg("Unseen-in-traindev vs Seen-in-traindev VMWEs", "Un-seen")
		result += self._html_macroavg("Variant-of-traindev vs Identical-to-traindev VMWEs", "Variation")
		result += self._html_macroavg("Single-token vs Multi-token VMWEs", "Number-of-tokens")

		# Language specific table
		result += (
			'<hr>\n'
			'<h1 style="color: steelblue;">Language-specific system ranking</h2>\n'
			'<br>\n'
			'<table class="styled-table">\n'
			'<thead>\n'
			'\t<tr>\n'
			'\t\t<th rowspan="2">Language</th>\n'
		)
		for header in ["Unseen MWE-based", "Global MWE-based", "Global Token-based"]:
			result += '\t\t<th colspan="3">' + header + '</th>\n'
		result += (
			'\t</tr>\n'
			'\t<tr>\n'
		)
		helper_list = [
			["Un-seen", "Unseen-in-traindev MWE-based"],
			["Global", "MWE-based"],
			["Global", "Tok-based"]
		] 
		result += 3 * (
			'\t\t<th>P</th>\n'
			'\t\t<th>R</th>\n'
			'\t\t<th>F</th>\n'
		)
		result += (
			'\t</tr>\n'
			'</thead>\n'
			'<tbody>\n'
		)
		for language in self.lang:
			result += (
				'\t<tr>\n'
				'\t\t<td>' + language + '</td>\n'
			)
			for labels in helper_list:
				for i in range(3):
					result += '\t\t<td>' + str(round(self.scores[language][labels[0]][labels[1]][i], 2)) + '</td>\n'
			result += '\t</tr>\n'
		result += (
			'</tbody>\n'
			'</table>\n'
			'<br>\n'
		)

		# Per VMWE category tables
		result += (
			'<hr>\n'
			'<h1 style="color: steelblue;">Results per VMWE category</h2>\n'
			'<br>\n'
		)
		for language in self.lang:
			result += (
				'<h2>' + language + '</h2>\n'
				'<table class="styled-table">\n'
				'<thead>\n'
				'\t<tr>\n'
				'\t\t<th rowspan="2">VMWEs</th>\n'
				'\t\t<th colspan="3">MWE-based</th>\n'
				'\t\t<th colspan="3">Token-based</th>\n'
				'\t</tr>\n'
				'\t<tr>\n'
			)
			result += 2 * (
				'\t\t<th>P</th>\n'
				'\t\t<th>R</th>\n'
				'\t\t<th>F</th>\n'
			)
			result += (
				'\t</tr>\n'
				'</thead>\n'
				'<tbody>\n'
			)
			for mwe in self.scores[language]["Per-category"].keys():
				result += (
					'\t<tr>\n'
					'\t\t<td>' + mwe + '</td>\n'
				)
				for _type in ["MWE-based", "Tok-based"]:
					result += (
						'\t\t<td>' + str(round(self.scores[language]["Per-category"][mwe][_type][0],2)) + '</td>\n'
						'\t\t<td>' + str(round(self.scores[language]["Per-category"][mwe][_type][1],2)) + '</td>\n'
						'\t\t<td>' + str(round(self.scores[language]["Per-category"][mwe][_type][2],2)) + '</td>\n'
					)
				result += '\t</tr>\n'
			result += (
				'</tbody>\n'
				'</table>\n'
				'<br>\n'
			)

		# Closing
		result += (
			'</body>\n'
			'</html>\n'
		)

		# Writing html file
		with open(html_path, 'w') as html_file:
			html_file.write(result)
