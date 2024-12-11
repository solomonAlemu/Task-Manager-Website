import csv

class CSVFileHandler:
    def __init__(self, file_path, has_header=True):
        """
        Initialize the CSVFileHandler.
        
        :param file_path: Path to the CSV file.
        :param has_header: Boolean indicating if the CSV file has a header row.
        """
        self.file_path = file_path
        self.has_header = has_header
        
    def open_file_with_fallback(self):
        """
        Open the file in append mode; if it doesn't exist, create a new one.
        
        :return: File object
        """
        try:
            self.file = open(self.file_path, "a", newline='', encoding='utf-8')
        except FileNotFoundError:
            self.file = open(self.file_path, "w", newline='', encoding='utf-8')
        return self.file
    def read_data(self):
        """
        Read the entire CSV file.
        
        :return: List of dictionaries if has_header is True, otherwise list of lists.
        """
        data = []
        with open(self.file_path, mode='r', newline='', encoding='utf-8') as file:
            if self.has_header:
                reader = csv.DictReader(file)
                for row in reader:
                    data.append(row)
            else:
                reader = csv.reader(file)
                for row in reader:
                    data.append(row)
        return data

    def write_data(self, data, headers=None):
        """
        Write data to the CSV file, overwriting existing content.
        
        :param data: List of dictionaries if has_header is True, otherwise list of lists.
        :param headers: List of headers if writing a CSV with headers.
        :return: None
        """
        with open(self.file_path, mode='w', newline='', encoding='utf-8') as file:
            if self.has_header and headers:
                writer = csv.DictWriter(file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(data)
            else:
                writer = csv.writer(file)
                writer.writerows(data)

    def append_data(self, data):
        """
        Append data to the CSV file.
        
        :param data: List of dictionaries if has_header is True, otherwise list of lists.
        :return: None
        """
        with open(self.file_path, mode='a', newline='', encoding='utf-8') as file:
            if self.has_header:
                headers = data[0].keys()
                writer = csv.DictWriter(file, fieldnames=headers)
                if file.tell() == 0:  # Check if the file is empty
                    writer.writeheader()
                writer.writerows(data)
            else:
                writer = csv.writer(file)
                writer.writerows(data)

    def flush_data(self):
        """
        Flush the data to the file, ensuring it's written to disk.
        
        :return: None
        """
        if self.file:
            self.file.flush()
            
    def close_file(self):
        """
        Close the file if it is open.
        
        :return: None
        """
        if self.file:
            self.file.close()
            self.file = None         