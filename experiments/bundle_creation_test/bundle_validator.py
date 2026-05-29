"""Codabench competition bundle validator.

Lint a generated bundle's competition.yaml + referenced files. Exit 0 on pass,
1 on validation/unexpected error. Stdout shows progress + the first error.

Vendored from the user-provided script — kept here so the experiment harness is
self-contained and the validation result is reproducible regardless of which
copy of the validator lives elsewhere in the repo.
"""
import os
import yaml
import datetime
import argparse
from dateutil import parser as date_parser


class BundleValidationError(Exception):
    pass


def get_datetime(field):
    if not field:
        return None
    if isinstance(field, (datetime.date, datetime.datetime)):
        if isinstance(field, datetime.date) and not isinstance(field, datetime.datetime):
            field = datetime.datetime.combine(field, datetime.time())
        return field
    try:
        return date_parser.parse(str(field))
    except (ValueError, TypeError):
        raise BundleValidationError(f"Invalid date format: {field}")


class BundleValidator:
    def __init__(self, bundle_path):
        self.bundle_path = bundle_path
        self.yaml_path = os.path.join(bundle_path, 'competition.yaml')
        self.competition_yaml = None

    def validate(self):
        print(f"[*] Validating bundle at: {self.bundle_path}")

        if not os.path.isdir(self.bundle_path):
            raise BundleValidationError(f"Bundle path does not exist or is not a directory: {self.bundle_path}")

        if not os.path.exists(self.yaml_path):
            raise BundleValidationError("competition.yaml not found in bundle root.")

        with open(self.yaml_path, 'r') as f:
            try:
                self.competition_yaml = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise BundleValidationError(f"Error parsing competition.yaml: {e}")

        self._check_required_fields()
        self._validate_image()
        self._validate_pages()
        self._validate_tasks()
        # self._validate_solutions()
        self._validate_terms()
        self._validate_phases()
        self._validate_leaderboards()

        print("[+] Bundle is valid!")

    def _check_required_fields(self):
        required = ['title', 'image', 'tasks', 'phases', 'leaderboards', 'pages', 'terms', 'docker_image']
        for field in required:
            if field not in self.competition_yaml:
                raise BundleValidationError(f"Missing required field: {field}")

    def _validate_image(self):
        image = self.competition_yaml.get('image')

        if not image:
            raise BundleValidationError("Image field is missing in competition YAML")

        allowed_extensions = {'.jpg', '.jpeg', '.png'}
        _, ext = os.path.splitext(image.lower())
        if ext not in allowed_extensions:
            raise BundleValidationError(
                f"Invalid image format: {image}. Only JPG, JPEG and PNG are allowed."
            )

        image_path = os.path.join(self.bundle_path, image)
        if not os.path.exists(image_path):
            raise BundleValidationError(f"Logo/Image not found: {image}")

    def _validate_pages(self):
        pages = self.competition_yaml.get('pages')

        if not pages:
            raise BundleValidationError("At least one page must be defined in 'pages'.")

        if not isinstance(pages, list):
            raise BundleValidationError("'pages' must be a list.")

        for i, page in enumerate(pages):
            title = page.get('title')
            file_name = page.get('file')

            if not title:
                raise BundleValidationError(
                    f"Page at index {i} missing or empty 'title' field."
                )

            if not file_name:
                raise BundleValidationError(
                    f"Page at index {i} missing or empty 'file' field."
                )

            page_path = os.path.join(self.bundle_path, file_name)
            if not os.path.exists(page_path):
                raise BundleValidationError(f"Page file not found: {file_name}")

            if os.path.getsize(page_path) == 0:
                raise BundleValidationError(f"Page file is empty: {file_name}")

    def _validate_tasks(self):
        tasks = self.competition_yaml.get('tasks')
        if not tasks:
            raise BundleValidationError("No tasks listed in competition.yaml")

        seen_indexes = set()
        for task in tasks:
            index = task.get('index')
            if index is None:
                raise BundleValidationError(f"Task '{task.get('name')}' missing 'index'.")

            if index in seen_indexes:
                raise BundleValidationError(f"Duplicate task index: {index}")
            seen_indexes.add(index)

            if 'key' in task:
                continue  # Existing task reference

            # Check scoring program
            # Required field
            scoring_program = task.get('scoring_program')
            if not scoring_program:
                raise BundleValidationError(
                    f"Task {index} missing scoring_program."
                )

            scoring_path = os.path.join(self.bundle_path, scoring_program)
            if not os.path.exists(scoring_path):
                raise BundleValidationError(
                    f"Task {index} scoring_program not found: {scoring_program}"
                )

            # Optional fields
            for file_type in ['ingestion_program', 'input_data', 'reference_data']:
                file_name = task.get(file_type)
                if file_name:
                    file_path = os.path.join(self.bundle_path, file_name)
                    if not os.path.exists(file_path):
                        raise BundleValidationError(
                            f"Task {index} {file_type} not found: {file_name}"
                        )

    # def _validate_solutions(self):
    #     solutions = self.competition_yaml.get('solutions', [])
    #     seen_indexes = set()
    #     for sol in solutions:
    #         index = sol.get('index')
    #         if index is None:
    #             raise BundleValidationError("Solution missing 'index'.")
    #         if index in seen_indexes:
    #             raise BundleValidationError(f"Duplicate solution index: {index}")
    #         seen_indexes.add(index)

    #         task_pointers = sol.get('tasks', [])
    #         if not task_pointers:
    #             raise BundleValidationError(f"Solution {index} has no tasks associated.")

    #         # Check if tasks exist in YAML
    #         task_indexes = [t.get('index') for t in self.competition_yaml.get('tasks', [])]
    #         for tp in task_pointers:
    #             if tp not in task_indexes:
    #                 raise BundleValidationError(f"Solution {index} references non-existent task index: {tp}")

    #         if 'key' not in sol:
    #             path = sol.get('path')
    #             if not path:
    #                 raise BundleValidationError(f"Solution {index} missing 'path'.")
    #             if not os.path.exists(os.path.join(self.bundle_path, path)):
    #                 raise BundleValidationError(f"Solution {index} file not found: {path}")

    def _validate_terms(self):
        terms_path = self.competition_yaml.get('terms')
        if not terms_path:
            raise BundleValidationError("Missing 'terms' field in competition.yaml")

        full_path = os.path.join(self.bundle_path, terms_path)
        if not os.path.exists(full_path):
            raise BundleValidationError(f"Terms file not found: {terms_path}")

        if os.path.getsize(full_path) == 0:
            raise BundleValidationError(f"Terms file is empty: {terms_path}")

    def _validate_phases(self):
        phases = self.competition_yaml.get('phases', [])
        if not phases:
            raise BundleValidationError("Competition must have at least one phase.")

        sorted_phases = sorted(phases, key=lambda p: p.get('index', 0))

        for i, phase in enumerate(sorted_phases):
            if 'tasks' not in phase:
                raise BundleValidationError(f"Phase {phase.get('index')} missing 'tasks'.")

            # Check public_data and starting_kit
            for key in ['public_data', 'starting_kit']:
                f_name = phase.get(key)
                if f_name:
                    if not os.path.exists(os.path.join(self.bundle_path, f_name)):
                        raise BundleValidationError(f"Phase {i} {key} file not found: {f_name}")

            # Date validation
            start = get_datetime(phase.get('start'))
            end = get_datetime(phase.get('end'))

            if i > 0:
                prev_phase = sorted_phases[i-1]
                prev_end = get_datetime(prev_phase.get('end'))

                if prev_end is None:
                    raise BundleValidationError(f"Phase {prev_phase.get('index')} must have an end date because there is a phase after it.")

                if start < prev_end:
                    raise BundleValidationError(f"Phases must be sequential. Phase {phase.get('index')} starts before Phase {prev_phase.get('index')} ends.")
                if start == prev_end:
                    raise BundleValidationError(f"Phase {phase.get('index')} should start after Phase {prev_phase.get('index')} has ended (dates conflict).")

    def _validate_leaderboards(self):
        leaderboards = self.competition_yaml.get('leaderboards')

        if not leaderboards:
            raise BundleValidationError(
                "Missing or empty 'leaderboards' in competition.yaml"
            )

        if not isinstance(leaderboards, list):
            raise BundleValidationError("'leaderboards' must be a list")

        leaderboard_indexes = set()

        for i, leaderboard in enumerate(leaderboards):

            if not isinstance(leaderboard, dict):
                raise BundleValidationError(
                    f"Leaderboard at index {i} must be an object"
                )

            # Required leaderboard fields
            index = leaderboard.get('index')
            title = leaderboard.get('title')
            key = leaderboard.get('key')
            submission_rule = leaderboard.get('submission_rule')
            columns = leaderboard.get('columns')

            if index is None:
                raise BundleValidationError(
                    f"Leaderboard at position {i} missing 'index'"
                )

            if index in leaderboard_indexes:
                raise BundleValidationError(
                    f"Duplicate leaderboard index: {index}"
                )

            leaderboard_indexes.add(index)

            if not title:
                raise BundleValidationError(
                    f"Leaderboard {index} missing or empty 'title'"
                )

            if not key:
                raise BundleValidationError(
                    f"Leaderboard {index} missing or empty 'key'"
                )

            if not submission_rule:
                raise BundleValidationError(
                    f"Leaderboard {index} missing or empty 'submission_rule'"
                )

            if not columns:
                raise BundleValidationError(
                    f"Leaderboard {index} must have at least one column"
                )

            if not isinstance(columns, list):
                raise BundleValidationError(
                    f"'columns' in leaderboard {index} must be a list"
                )

            column_indexes = set()

            for col_i, column in enumerate(columns):

                if not isinstance(column, dict):
                    raise BundleValidationError(
                        f"Column at position {col_i} in leaderboard {index} must be an object"
                    )

                col_index = column.get('index')
                col_title = column.get('title')
                col_key = column.get('key')

                if col_index is None:
                    raise BundleValidationError(
                        f"Column at position {col_i} in leaderboard {index} missing 'index'"
                    )

                if col_index in column_indexes:
                    raise BundleValidationError(
                        f"Duplicate column index {col_index} in leaderboard {index}"
                    )

                column_indexes.add(col_index)

                if not col_title:
                    raise BundleValidationError(
                        f"Column {col_index} in leaderboard {index} missing or empty 'title'"
                    )

                if not col_key:
                    raise BundleValidationError(
                        f"Column {col_index} in leaderboard {index} missing or empty 'key'"
                    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Validate Codabench competition bundle.')
    parser.add_argument('path', help='Path to the bundle folder')
    args = parser.parse_args()

    validator = BundleValidator(args.path)
    try:
        validator.validate()
    except BundleValidationError as e:
        print(f"[-] Validation Error: {e}")
        exit(1)
    except Exception as e:
        print(f"[-] Unexpected Error: {e}")
        exit(1)
