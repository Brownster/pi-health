from flask import Flask, jsonify, send_from_directory
import os

app = Flask(__name__, static_folder='static')

@app.route('/')
def serve_frontend():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/stats', methods=['GET'])
def api_stats():
    stats = get_system_stats()
    return jsonify(stats)
