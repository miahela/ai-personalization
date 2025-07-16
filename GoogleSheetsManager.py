from google.oauth2.service_account import Credentials
import gspread

class GoogleSheetsManager:
    def __init__(self, credentials_file, sheet_name):
        self.credentials_file = credentials_file
        self.client = self.authenticate_gspread()
        self.worksheet = self.get_worksheet(sheet_name, 0)

    def authenticate_gspread(self):
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            self.credentials_file, scopes=scope
        )
        return gspread.authorize(creds)

    def get_worksheet(self, sheet_name, worksheet_index):
        sheet = self.client.open(sheet_name)
        return sheet.get_worksheet(worksheet_index)

    def get_worksheet_data(self):
        return self.worksheet.get_all_values()
    
    def get_emails_without_status(self):
        emails_without_status = []
        data = self.get_worksheet_data()
        for row in data:
            if len(row) > 1 and row[1] == "":
                emails_without_status.append(row[0])
        return emails_without_status

    def update_email_status(self, email, status):
        data = self.worksheet.get_all_values()
        for idx, row in enumerate(data):
            if row[0] == email:
                self.worksheet.update_cell(idx + 1, 2, status)
                break

    def update_email_statuses(self, updates):
        range_string = 'A:B'  
        data = self.worksheet.get(range_string)

        cell_list = []

        email_to_row = {row[0]: index + 1 for index, row in enumerate(data) if row[0] in dict(updates)}

        for email, status in updates:
            row_index = email_to_row.get(email)
            if row_index:
                cell = gspread.Cell(row_index, 2, status)  
                cell_list.append(cell)

        if cell_list:
            self.worksheet.update_cells(cell_list)
