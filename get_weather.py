from google import genai





client = genai.Client()

response = client.models.generate_content(
    model = 'gemini-2.0-flash',
    contents = ' What is the 35th biggest city in Germany?'
)
