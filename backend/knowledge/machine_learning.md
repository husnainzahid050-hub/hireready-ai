---
competency: machine_learning
title: Machine Learning Fundamentals
levels: [junior, mid]
---

# Machine Learning Fundamentals

## What interviewers evaluate

- Understanding of supervised vs unsupervised learning and common algorithms.
- Overfitting, underfitting, and the bias-variance tradeoff, with practical remedies.
- Correct evaluation: train/validation/test splits, cross-validation, avoiding data leakage.
- Choosing metrics that match the business problem (precision, recall, F1, ROC-AUC, RMSE).
- For mid level: feature engineering, handling class imbalance, model monitoring and drift.

## Question bank

### Junior

#### What is overfitting and how do you prevent it?

**Strong answer includes:** the model learns noise in the training data, so training performance is
high but validation performance is poor; detect via a gap between train and validation scores;
remedies include more data, regularization (L1/L2), simpler models, early stopping, dropout for
neural nets, and cross-validation; gives an example from a project.

**Common weak answers:** "When the model is too good" with no detection method or remedies.

**Red flags:** evaluates only on training data; tunes hyperparameters on the test set.

#### Explain precision and recall. When do you prefer one over the other?

**Strong answer includes:** precision = of predicted positives, how many are correct; recall = of
actual positives, how many were found; prefer recall when missing positives is costly (disease
screening, fraud), precision when false alarms are costly (spam filter on important mail);
F1 balances both; accuracy misleads on imbalanced data.

**Common weak answers:** recites formulas without a use case.

**Red flags:** uses accuracy on a 99:1 imbalanced dataset and calls the model good.

#### Why do we split data into train, validation, and test sets?

**Strong answer includes:** train to fit, validation to tune hyperparameters and choose models, test
held out once for an unbiased final estimate; k-fold cross-validation when data is small; time
series needs time-ordered splits.

**Common weak answers:** "To test the model" without the role of validation.

**Red flags:** random-splits time series data; scales features before splitting (leakage).

### Mid

#### Explain the bias-variance tradeoff.

**Strong answer includes:** bias is error from overly simple assumptions (underfitting); variance is
sensitivity to the training sample (overfitting); total error balances both; model complexity,
regularization, and ensembling move along the tradeoff (bagging reduces variance, boosting reduces
bias); uses learning curves to diagnose.

**Common weak answers:** defines both terms but cannot connect them to model choices.

**Red flags:** says more complex models are always better with more compute.

#### What is data leakage? Give an example.

**Strong answer includes:** information unavailable at prediction time leaks into training, inflating
scores; examples: fitting a scaler on the full dataset before splitting, using a feature derived
from the target, duplicate users in train and test; fix with pipelines (`sklearn.pipeline`) and
careful splits.

**Common weak answers:** "When data is leaked online."

**Red flags:** never questions suspiciously high validation scores.

## Scoring anchors

Example question: "Your model has 98% training accuracy and 70% validation accuracy. What is going on?"

### Score 1/5

"The model is good because training accuracy is high." Misreads the situation.

### Score 3/5

"It is overfitting, so I would use regularization." Correct diagnosis and one remedy, but no
reasoning about data, model complexity, or verifying the fix.

### Score 5/5

"The large train/validation gap means overfitting. First I would check for leakage or a split
mismatch. Then try stronger regularization or a simpler model, get more data or augment, and use
cross-validation to confirm the gap closes. I would also check if accuracy is even the right metric
if classes are imbalanced." Accurate diagnosis, prioritized steps, verification, metric awareness.

## Resources

- [Google Machine Learning Crash Course](https://developers.google.com/machine-learning/crash-course): free official course.
- [scikit-learn User Guide](https://scikit-learn.org/stable/user_guide.html): algorithms and practical usage.
- [Cross-validation in scikit-learn](https://scikit-learn.org/stable/modules/cross_validation.html): evaluation done right.
