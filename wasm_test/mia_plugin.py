import os
import json
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from tensorflow import keras
import extism

@extism.plugin_fn
def run_assessment():
    input_data = json.loads(extism.input())
    model_path = input_data.get("model_path", "trained_model.keras")

    # Load pre-trained Keras model
    model = keras.models.load_model("data/trained_model.keras")

    # Generate synthetic-like vibration data similar to real input
    # For demo purposes, generate 1000 sequences of length 300 with 3 vibration channels
    n_samples = 1000
    sequence_length = 300
    X = np.random.normal(0, 1, (n_samples, sequence_length, 3))
    y = np.random.randint(0, 2, n_samples)

    # Split into member (train) and non-member (test) data
    X_member, X_nonmember = X[:500], X[500:]
    y_member, y_nonmember = y[:500], y[500:]

    # Generate shadow model (clone and retrain on shadow data)
    shadow_model = keras.models.clone_model(model)
    shadow_model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])
    shadow_model.fit(X_member, y_member, epochs=5, batch_size=16, verbose=0)

    def get_outputs(m, X, label):
        probs = m.predict(X, verbose=0).reshape(-1, 1)
        return np.hstack([probs, np.full((len(X), 1), label)])

    # Create attack training set
    train_in = get_outputs(shadow_model, X_member, 1)
    train_out = get_outputs(shadow_model, X_nonmember, 0)
    train_all = np.vstack([train_in, train_out])
    attack_X = train_all[:, :-1]
    attack_y = train_all[:, -1]

    # Train attack model
    attack_model = RandomForestClassifier(n_estimators=100)
    attack_model.fit(attack_X, attack_y)

    # Evaluate against target model
    eval_in = get_outputs(model, X_member, 1)
    eval_out = get_outputs(model, X_nonmember, 0)
    eval_all = np.vstack([eval_in, eval_out])
    eval_X = eval_all[:, :-1]
    eval_y = eval_all[:, -1]

    predictions = attack_model.predict(eval_X)
    acc = accuracy_score(eval_y, predictions)

    result = {
        "attack_model_accuracy": float(acc),
        "attack_success_rate": float(np.mean(predictions == eval_y)),
        "mia_vulnerability": "vulnerable" if acc > 0.6 else "robust"
    }

    extism.output(result)
