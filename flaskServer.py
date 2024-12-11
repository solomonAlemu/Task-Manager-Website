from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')  # This will serve at http://127.0.0.1:5000
def home():
    return render_template('webscraper.html')  # Renders the 'webscraper.html' file

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5001, threaded=True)
