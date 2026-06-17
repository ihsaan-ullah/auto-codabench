# Evaluation

## The problem

This is a regression problem: predict the time a patient survives after
admission to a hospital. Each patient is characterised by:

- Age
- Ethnicity (one-hot encoded)
- Gender
- Blood pressure (systolic and diastolic)
- Glycated-hemoglobin concentration
- Body Mass Index (BMI)

That is 10 features in total, used to predict the pair:

- **Target** — the survival time to predict.
- **Event** — whether the observation is censored (`0` if the patient left the
  study or it stopped too early, `1` otherwise).

You are given a training matrix `X_train` of shape 19 297 × 10 and a label
array `y_train` of shape 19 297 × 2. You must train a model that predicts labels
for the two held-out matrices `X_valid` and `X_test`.

## Evaluation metric

Submissions are scored with the **concordance index** (c-index). The c-index is
a global measure of a survival model's predictive ability: it is the fraction of
comparable patient pairs for which the patient with the higher observed survival
time also receives the higher predicted probability of survival. **Higher is
better** (the leaderboard sorts the score in descending order); high values mean
the model assigns higher survival probabilities to patients who in fact survive
longer.

## Phases

There are two phases:

- **Phase 1 — development.** You are given labelled training data and unlabelled
  validation and test data. Make predictions for both; you receive feedback on
  the validation set only. The score of your **last** submission is shown on the
  leaderboard.
- **Phase 2 — final.** You do not need to do anything: your last Phase-1
  submission is automatically forwarded, and your test-set score appears once
  the organizers finish checking submissions.

During the competition you may submit only prediction results (no code), a
pre-trained model, or a model that is trained and tested in the sandbox. All
submissions are evaluated with the concordance index above.
