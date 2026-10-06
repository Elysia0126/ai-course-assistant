# Overfitting and Regularization — Study Guide

These notes accompany Lecture 6 of Machine Learning Foundations.

## Bias and Variance

The bias-variance trade-off describes how prediction error splits into two sources. Bias is the error caused by
overly simple assumptions in the model; high-bias models underfit. Variance is the error caused by sensitivity to
small fluctuations in the training set; high-variance models overfit.

## Overfitting

Overfitting is when a model learns noise and accidental patterns in the training data and therefore performs poorly
on unseen data. The classic symptom is a training loss that keeps falling while the validation loss starts to rise.
Underfitting is the opposite: the model is too simple to capture the structure of the data.

## L2 Regularization (Weight Decay)

L2 regularization adds a penalty proportional to the squared magnitude of the weights to the loss:
`L_total = L_data + lambda * ||w||^2`. Larger values of lambda push weights towards zero and produce smoother
models. In neural networks this is usually implemented as weight decay.

## L1 Regularization

L1 regularization adds a penalty proportional to the absolute value of the weights. Unlike L2, it drives many
weights exactly to zero, which produces sparse models and acts as a form of feature selection.

## Dropout

Dropout is a regularization technique that randomly sets a fraction of activations to zero during training. A
typical dropout rate is 0.5 for fully connected layers. At test time all units are used and activations are scaled
so their expected value matches training.

## Early Stopping

Early stopping is a strategy that halts training when the validation loss stops improving for a number of epochs,
called the patience. The weights from the best validation epoch are restored at the end.

## Cross-Validation

k-fold cross-validation splits the data into k folds, trains on k-1 folds and evaluates on the remaining fold,
rotating k times. The average score is a more reliable estimate of generalization than a single split, and it is
the standard way to choose hyperparameters such as lambda.

## Data Augmentation

Data augmentation creates new training examples by applying label-preserving transformations, such as flips,
crops and colour jitter for images. More varied data reduces variance without changing the model.
