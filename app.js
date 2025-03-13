// app.js

const express = require('express');
const app = express();
const port = 3000;

app.use(express.json()); // Middleware to parse JSON requests

app.get('/', (req, res) => {
  res.send('Welcome to the REST API of the inTrust tool!');
});

app.listen(port, () => {
  console.log(`Server is running on http://localhost:${port}`);
});

app.get('/intents', (req, res) => {
    const intents = [
      { id: 1, name: 'Intent 1' },
      { id: 2, name: 'Intent 2' },
    ];
    res.json(intents);
  });

app.get('/intents/:id', (req, res) => {
    const intents = [
        { id: 1, name: 'Intent 1' },
        { id: 2, name: 'Intent 2' },
    ];
    const intent = intents.find((u) => u.id === parseInt(req.params.id));
    if (intent) {
      res.json(intent);
    } else {
      res.status(404).send('Intent not found');
    }
  });