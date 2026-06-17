# Data

The data come from the Continuous NHANES survey (1999–2007); see the
[NHANES site](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/default.aspx).

Go to the **Files** tab to download the data and the starting kit. The starting
kit contains a very small subset of the data for debugging. To prepare a real
submission, use the large dataset downloaded separately — for the large dataset
you do **not** have the labels.

Each patient is described by 10 features (age, ethnicity as a one-hot encoding,
gender, systolic and diastolic blood pressure, glycated-hemoglobin
concentration, and body-mass index). The training set has 19 297 patients; you
predict labels for the held-out validation and test matrices.

## Licence

The underlying NHANES dataset is released by the U.S. CDC / National Center for
Health Statistics and is in the **public domain** (U.S. Government work, no
usage restrictions). The aggregated files distributed with this competition
follow the same terms.
