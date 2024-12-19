import os
import subprocess

def generate_requirements_file(output_file="requirements.txt"):
    try:
        # Get the list of installed packages with their versions
        result = subprocess.run(["pip", "freeze"], stdout=subprocess.PIPE, text=True, check=True)
        packages = result.stdout

        # Write the output to a requirements.txt file
        with open(output_file, "w") as file:
            file.write(packages)
        print(f"Requirements file generated successfully at: {os.path.abspath(output_file)}")
    except subprocess.CalledProcessError as e:
        print(f"Error generating requirements file: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    generate_requirements_file()
