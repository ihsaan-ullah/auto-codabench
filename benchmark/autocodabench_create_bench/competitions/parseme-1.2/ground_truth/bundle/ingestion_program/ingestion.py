# Imports
import os
import sys


# Paths
input_dir = '/app/input_data/'
output_dir = '/app/output/'
program_dir = '/app/program/'
submission_dir = '/app/ingested_program'
sys.path.append(output_dir)
sys.path.append(program_dir)
sys.path.append(submission_dir)


# Constants
LANGUAGES = ['DE', 'EL', 'EU', 'FR', 'GA', 'HE', 'HI', 'IT', 'PL', 'PT', 'RO', 'SV', 'TR', 'ZH']


# Main
if __name__ == "__main__":
	from model import Model
	for lang in LANGUAGES:
		print("Producing results for language: ", lang)
		train_path = os.path.join(input_dir, lang, 'train.cupt')
		dev_path = os.path.join(input_dir, lang, 'dev.cupt')
		test_path = os.path.join(input_dir, lang, 'test.blind.cupt')
		output_path = os.path.join(output_dir, lang, 'test.system.cupt')
		if not os.path.isfile(train_path) or not os.path.isfile(dev_path) or not os.path.isfile(test_path):
			print('ERROR: The ingestion program was not able to retrieve the input data')
			sys.exit(1)
		m = Model(lang)
		m.fit(train_path, dev_path)
		m.predict(test_path, output_path)

