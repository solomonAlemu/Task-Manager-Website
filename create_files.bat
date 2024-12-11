@echo off
mkdir task_manager
cd task_manager

mkdir static
cd static

mkdir css
cd css
echo. > styles.css
cd ..

mkdir js
cd js
echo. > scripts.js
cd ..
cd ..

mkdir templates
cd templates
echo. > base.html
echo. > index.html
echo. > task_details.html
echo. > monthly_progress.html
cd ..

echo. > app.py
echo. > models.py
echo. > requirements.txt
echo. > database.db

echo File structure created successfully.
pause
