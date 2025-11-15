const express = require('express');
const cors = require('cors');
const path = require('path');
const app = express();
const port = 8000;


app.use(cors())

app.use(express.static(path.join(__dirname, 'frontend'), {extensions:['html']}));

app.listen(port, host="0.0.0.0",  () => {
    console.log("app listening on port" + port);
});

