---
competency: deep_learning
title: Deep Learning
levels: [junior, mid]
---

# Deep Learning

## What interviewers evaluate

- How neural networks learn: forward pass, loss, backpropagation, gradient descent.
- Common architectures (MLP, CNN, RNN/LSTM, Transformer) and what problems they suit.
- Training practicalities: learning rate, batch size, normalization, dropout, early stopping.
- Transfer learning and fine-tuning pretrained models.
- For mid level: debugging training, vanishing/exploding gradients, attention, efficient inference.

## Question bank

### Junior

#### Explain backpropagation in simple terms.

**Strong answer includes:** after the forward pass computes the loss, backpropagation applies the
chain rule to compute the gradient of the loss with respect to every weight, layer by layer from
output to input; the optimizer (e.g. SGD, Adam) then updates weights in the direction that reduces
loss, scaled by the learning rate.

**Common weak answers:** "The network goes backwards to fix errors" with no gradients or chain rule.

**Red flags:** confuses backpropagation with the optimizer or with inference.

#### Why do we use activation functions?

**Strong answer includes:** without non-linear activations, stacked layers collapse into a single
linear transformation; ReLU is the common default (cheap, reduces vanishing gradients); sigmoid or
softmax at the output for probabilities.

**Common weak answers:** "To activate the neurons."

**Red flags:** cannot say what happens without them.

#### What is transfer learning and why is it useful?

**Strong answer includes:** reuse a model pretrained on a large dataset (e.g. ImageNet, a language
model) and fine-tune it on a smaller task-specific dataset; saves data and compute; often freeze
early layers and train the head first; mentions their own project if any.

**Common weak answers:** "Using someone else's model."

**Red flags:** fine-tunes with a very high learning rate and is surprised by poor results.

### Mid

#### Your training loss is not decreasing. How do you debug it?

**Strong answer includes:** overfit a tiny batch first to verify the pipeline; check data and label
alignment; check the learning rate (too high diverges, too low stalls); inspect gradient norms for
vanishing/exploding; verify the loss function matches the output (logits vs probabilities);
normalize inputs; use a known-good baseline.

**Common weak answers:** "Train for more epochs."

**Red flags:** changes many hyperparameters at once with no hypothesis.

#### Explain self-attention in Transformers.

**Strong answer includes:** each token produces query, key, and value vectors; attention weights are
softmax of scaled query-key dot products; output is a weighted sum of values, letting every token
use context from every other token in parallel; multi-head attention learns different relations;
cost is quadratic in sequence length.

**Common weak answers:** "Attention lets the model focus on important words" with no mechanism.

**Red flags:** thinks Transformers process tokens one at a time like RNNs during training.

## Scoring anchors

Example question: "What is dropout and why does it help?"

### Score 1/5

"Dropout removes bad data from the dataset." Incorrect.

### Score 3/5

"Dropout randomly turns off neurons during training to reduce overfitting." Correct but shallow.

### Score 5/5

"During training, dropout zeroes a random fraction of activations each step, so the network cannot
rely on any single neuron and learns more robust features, acting like an ensemble of
sub-networks. At inference it is turned off and activations are scaled accordingly. I used 0.3
dropout in my CNN project and it closed the gap between train and validation accuracy." Accurate
mechanism, train vs inference detail, concrete evidence.

## Resources

- [Dive into Deep Learning](https://d2l.ai/): free interactive textbook with code.
- [PyTorch tutorials](https://docs.pytorch.org/tutorials/): official hands-on tutorials.
- [TensorFlow tutorials](https://www.tensorflow.org/tutorials): official guides and examples.
