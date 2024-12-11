from bs4 import BeautifulSoup


class XMLHandler:

    def __init__(self, xml_file):
        if xml_file is not None:
            with open(xml_file, 'r', encoding='utf-8') as xml: 
                self.xml_file = BeautifulSoup(xml, "xml")
        else:pass   
        
    def read(self):
        with open(self.xml_file, 'r', encoding='utf-8') as f:
            self.xml_file = BeautifulSoup(f.read(), "xml")

    def write(self, data):
        with open(self.data, 'W', encoding='utf-8') as f:
            f.write(data)
            
    def write_data_to_tag(self, tag_name, data):
        # Writes the given data to the tag with the given name.
        self.tag = self.xml_file.find(tag_name)
        self.tag .text = data
        
    def add_new_tag(self, tag_name, content):
        # Adds a new tag with the given name and content.
        new_tag = self.xml_file.new_tag(tag_name)
        new_tag.append(content)
        self.xml_file.append(new_tag)
          
    def get_all_tag_texts(self, tag_name):
        return    [tag.text for tag in self.xml_file.find_all(tag_name)]
    
    def find__XML_tag(self, tag_name):
        return self.xml_file.find(tag_name)
    
    def find_tag_in_XML_tag(self, tag_name1,tag_name2):
        return tag_name1.find(tag_name2)
        
    def find__XML_tag_with_attribuite(self, tag_name,attribute):
        return self.xml_file.find(tag_name)[attribute]   
     
    def find__XML_tags(self, tag_name):
        return self.xml_file.find_all(tag_name)
     
    def get_tag_text(self, tag_name):
        return self.xml_file.find(tag_name).text    

    def find_tag_text_in_XML_tag(self, tag_name1,tag_name2):
        return tag_name1.find(tag_name2).text
                                      
    def get_xml_tag_with_text_value(self, text_value):
        for tag in self.xml_file.find_all():
            if tag.text == text_value:
                return tag
        return None
    
    def get_xml_tag_with_attribute_value(self, attribute_name,attribute_value):
        for tag in self.xml_file.find_all():
            if tag.get(attribute_name) == attribute_value:
                return tag
            return None  
    
    def get_number_of_tags(self, tag_name):
        return len(self.xml_file.find_all(tag_name))
    
    def get_all_number_of_tags(self, tag_name):
        return  [tag.text for tag in self.xml_file.find_all(tag_name)]
    
    
