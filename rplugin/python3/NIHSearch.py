import pynvim
import tempfile
import requests
import threading
import pdfplumber
from Bio import Entrez
from pynvim.api import NvimError

@pynvim.plugin
class NIHSearch(object):
    def __init__(self, nvim):
        self.nvim = nvim
        self.sum = []
        self.active_sum = None
        Entrez.email = "NIHSearch@nvim.com"

    #####################################################################################################################################

    def IsResponsePdf(self, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
        }

        response = requests.get(url, headers=headers)
        content_type = response.headers.get('Content-Type', '').lower()

        if 'application/pdf' in content_type:
            return True
        
        if response.content.startswith(b'%PDF'):
            return True
        
        return False

    def GetPaperUrl(self, doi):
        url = f"https://api.unpaywall.org/v2/{doi}?email=nihsearch@nvim.com"
        response = requests.get(url)
    
        if response.status_code != 200: 
            return None 
    
        if response.json(): 
            response = response.json()
        else:
            return None

        if not response.get("is_oa"):
            return None
        
        best_location = response.get("best_oa_location")
        pdf_url = best_location.get("url_for_pdf")
        if not pdf_url:
            return None
        
        return pdf_url

    def GetPdfData(self, pdf_url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
        }

        response = requests.get(pdf_url, headers=headers)
        pdf_data = response.content
        return pdf_data

    def FormatPdfData(self, pdf_data):
        formated_pdf_data = None
    
        try:
            with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
                formated_pdf_data = []

                for i, page in enumerate(pdf.pages):
                    text = page.extract_text(
                        layout=False,         # Try False first, then True if needed
                        x_tolerance=1.5,     # LOWER this number (default is 3). Forces spaces in smaller gaps.
                        y_tolerance=3,       # Keeps rows from overlapping
                        keep_blank_chars=True # Forces the engine to respect empty intervals
                    )
                    formated_pdf_data.append(text if text else "[No text]")
        except:
            print("PrintPdfData Exception: Make sure contrents are in pdf format")
    
        return formated_pdf_data
    ###########################################################################################################################################3

    @pynvim.command("CloseActiveWindow", sync=True)
    def CloseActiveWindow(self):
        try:
            currWin = self.nvim.api.get_current_win()
            self.nvim.async_call(lambda: self.nvim.err_write(f"Active window handle just prior to close attempt: {currWin}"))
            self.nvim.api.win_close(currWin, False)
        except NvimError as e:
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error closing window: {e}"))
    
    @pynvim.command("CloseActiveWindowAndResetActiveSum", sync=True)
    def CloseActiveWindowAndResetActiveSum(self):
        try:
            currWin = self.nvim.api.get_current_win()
            self.nvim.async_call(lambda: self.nvim.err_write(f"Active window handle just prior to close attempt: {currWin}"))
            self.nvim.api.win_close(currWin, False)
            self.active_sum = None
        except NvimError as e:
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error closing window: {e}"))

    def SearchMapping(self, buf):
        opts = {'noremap': True, 'silent': True}
        buf.api.set_keymap('n', '<CR>', ':DisplayPaperSummary<CR>', opts)
        buf.api.set_keymap('n', '<LeftMouse>', '<LeftMouse>:DisplayPaperSummary<CR>', opts)
        buf.api.set_keymap('n', '<Esc>', ':CloseActiveWindow<CR>', opts)
    
    def SummaryMapping(self, buf):
        opts = {'noremap': True, 'silent': True}
        buf.api.set_keymap('n', '<CR>', ':DisplayPaper<CR>', opts)
        buf.api.set_keymap('n', '<LeftMouse>', '<LeftMouse>:DisplayPaper<CR>', opts)
        buf.api.set_keymap('n', '<Esc>', ':CloseActiveWindowAndResetActiveSum<CR>', opts)

    def PaperPreviewMapping(self, buf):
        opts = {'noremap': True, 'silent': True}
        #buf.api.set_keymap('n', '<LeftMouse>', '<LeftMouse>:OpenPaperInNewWindow<CR>', opts)
        buf.api.set_keymap('n', '<Esc>', ':CloseActiveWindow<CR>', opts)

    def ReturnCleanAbstractXml(self, xml):
        abstract_text = 'No Abstract Found'
        articles = xml.get("PubmedArticle", [])

        if articles:
            medline = articles[0].get("MedlineCitation", {})
            article_info = medline.get("Article", {})
            title = article_info.get("ArticleTitle", "No Title Found")
    
            abstract_dict = article_info.get("Abstract", {})
            if abstract_dict:
                fragments = abstract_dict.get("AbstractText", [])
                abstract_text = " ".join(fragments)
    
        return abstract_text

    @pynvim.command("DisplayPaper", sync=True)
    def DisplayPaper(self):
        try:
            def updateUI():
                valRow = 6
                currBuf = self.nvim.api.get_current_buf()
                currWin = self.nvim.api.get_current_win()
                row, col = self.nvim.api.win_get_cursor(currWin)
                if (row == valRow):
                    # Will hold paper preview
                    # Create new buffer
                    paperPreviewBufHandle = self.nvim.api.create_buf(False, True)
                    self.PaperPreviewMapping(paperPreviewBufHandle)
                    paperPreviewBufHandle.options['buftype'] = 'nofile'
                    paperPreviewBufHandle.options['bufhidden'] = 'wipe'
                    paperPreviewBufHandle.options['filetype'] = 'markdown'
                    paperPreviewBufHandle.options['modifiable'] = True

                    # Put doi and name of paper in the new buffer
                    title = self.active_sum.get("Title", "N/A")
                    doi = self.active_sum.get("DOI", "N/A")
                    lines = []
                    # Sould display a loading screen
                    lines.append(f"DOI: {doi}")
                    lines.append("Pdf Contents:")
                    lines.append("-------------------------------")

                    ########################################################################################################################################
                    paper_url = self.GetPaperUrl(doi)
                    if paper_url:
                        is_pdf = self.IsResponsePdf(paper_url)
                        if is_pdf:
                            pdf_data = self.GetPdfData(paper_url)
                            formated_pdf_data = self.FormatPdfData(pdf_data)
                            if formated_pdf_data is not None:
                                lines.extend(formated_pdf_data)
                    else:
                        lines.append("Unable to retrieve paper")
                    ###################################################################################               
                    paperPreviewBufHandle[:] = lines
                    paperPreviewBufHandle.options['modifiable'] = False

                    # Create new window over other windows, fill this new window with paperPreviewBufHandle contents
                    winWidth = self.nvim.options['columns']
                    winHeight = self.nvim.options['lines']

                    config = {
                        'relative': 'editor',
                        'row': int(winHeight / 4),
                        'col': int(winWidth / 4),
                        'width': int(winWidth / 2),
                        'height': int(winHeight / 2),
                        'border': 'rounded', 
                        'anchor': 'NW',
                        'style': 'minimal',
                        'focusable': True,
                    }
                    self.nvim.command(':set linebreak')
                    self.nvim.command(':set breakindent')
                    paperPreviewWinHandle = self.nvim.api.open_win(paperPreviewBufHandle, True, config) # Keep this here, putting it within config dosent work
                    self.nvim.api.win_set_option(paperPreviewWinHandle, 'wrap', True)
                    self.nvim.api.set_current_win(paperPreviewWinHandle) 
            self.nvim.async_call(updateUI)
        except Exception as e:
            err_msg = str(e)
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error: {err_msg}\n"))

    @pynvim.command("DisplayPaperSummary", sync=True)
    def DisplayPaperSummary(self):
        try:
            def updateUI(): 
                valRow = [i for i in range(8, 123, 6)]
                currBuf = self.nvim.api.get_current_buf()
                currWin = self.nvim.api.get_current_win()
                row, col = self.nvim.api.win_get_cursor(currWin)
                if (row in valRow):
                    ind = valRow.index(row)
                    self.active_sum = self.sum[ind]

                    summaryBufHandle = self.nvim.api.create_buf(False, True)
                    self.SummaryMapping(summaryBufHandle)
                    summaryBufHandle.options['buftype'] = 'nofile'
                    summaryBufHandle.options['bufhidden'] = 'wipe'
                    summaryBufHandle.options['filetype'] = 'markdown'
                    summaryBufHandle.options['modifiable'] = True

                    title = self.active_sum.get('Title', 'N/A')
                    authors = self.active_sum.get('AuthorList', 'N/A')
                    datePublished = self.active_sum.get("PubDate", "N/A")
                    journal = self.active_sum.get("FullJournalName", "N/A")

                    # Abstract retrival and cleaning logic
                    paper_id = self.active_sum.get('Id')
                    paper_handle = Entrez.efetch(db='pubmed', id=paper_id, rettype="abstract", retmode="xml")
                    uncleaned_abstract_xml = Entrez.read(paper_handle)
                    paper_handle.close()
                    abstract = self.ReturnCleanAbstractXml(uncleaned_abstract_xml)

                    comment = self.active_sum.get("Comment", "N/A")
                    note = self.active_sum.get("Note", "N/A")

                    lines = []
                    lines.append(f"## {title}")
                    lines.append(f"**Date Published**: {datePublished}")
                    lines.append(f"**Journal**: {journal}")
                    lines.append(f"**Authors**: {', '.join(authors)}")
                    lines.append("")
                    lines.append("**View Full Text**")
                    lines.append("")
                    lines.append("Abstract")
                    lines.append("---")
                    lines.append(abstract) 
                    lines.append("")
                    lines.append("Comment")
                    lines.append("---")
                    lines.append(comment)
                    lines.append("")
                    lines.append("Note")
                    lines.append("---")
                    lines.append(note)

                    summaryBufHandle[:] = lines
                    summaryBufHandle.options['modifiable'] = False

                    # create new window thats overlayed over the search window & fill it with the contents of the summaryBufHandle
                    winWidth = self.nvim.options['columns']
                    winHeight = self.nvim.options['lines']

                    config = {
                        'relative': 'editor',
                        'row': int(winHeight / 4),
                        'col': int(winWidth / 4),
                        'width': int(winWidth / 2),
                        'height': int(winHeight / 2),
                        'border': 'rounded', 
                        'anchor': 'NW',
                        'style': 'minimal',
                        'focusable': True,
                    }
                    self.nvim.command(':set linebreak')
                    self.nvim.command(':set breakindent')
                    summaryWinHandle = self.nvim.api.open_win(summaryBufHandle, True, config) # Keep this here, putting it within config dosent work
                    self.nvim.api.win_set_option(summaryWinHandle, 'wrap', True)
                    self.nvim.api.set_current_win(summaryWinHandle) 

            self.nvim.async_call(updateUI)
        except Exception as e:
            err_msg = str(e)
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error: {err_msg}\n"))

    @pynvim.command('NIHSearch', nargs='+', sync=False)
    def nihSearch(self, args):
        if ("-h" in args):
            def helpMenu():
                def updateUI():
                    helpBufHandle = self.nvim.api.create_buf(False, True)
                    helpBufHandle.options['buftype'] = 'nofile'
                    helpBufHandle.options['bufhidden'] = 'wipe'
                    helpBufHandle.options['filetype'] = 'markdown'

                    lines = ["# NIHSearch Help Menu", "---", ""]

                    lines.append("## Description")
                    lines.append("NIHSearch.py allows users to query different NIH databases includeing pubmed, pubmed centeral, pubmed protein database, etc. In the floating window users are free to view a short description of each item returned from a query and open the associated file in a new buffer.")
                    lines.append("")

                    lines.append("## Usage")
                    lines.append("`:NIHSearch [db (optional)] [query]`")
                    lines.append("")
                    lines.append("- `db`: String, specifies what database to querry. Valid options inlcude pubmed, protein, nuccore, gene, snp, structure, pmc (for Pubmed-Central), genome, taxonomy, mesh, and  sra. This argument is set to 'pubmed' by default.")
                    lines.append("")
                    lines.append("- `query`: String, speficies the term to querry.")

                    helpBufHandle[:] = lines
                    helpBufHandle.options['modifiable'] = False

                    winWidth = self.nvim.options['columns']
                    winHeight = self.nvim.options['lines']

                    config = {
                        'relative': 'editor',
                        'row': int(winHeight / 4),
                        'col': int(winWidth / 4),
                        'width': int(winWidth / 2),
                        'height': int(winHeight / 2),
                        'border': 'rounded', 
                        'anchor': 'NW',
                        'style': 'minimal',
                        'focusable': True,
                    }
                    self.nvim.command(':set linebreak')
                    self.nvim.command(':set breakindent')
                    helpWinHandle = self.nvim.api.open_win(helpBufHandle, True, config) # Keep this here, putting it within config dosent work
                    self.nvim.api.win_set_option(helpWinHandle, 'wrap', True)

                self.nvim.async_call(updateUI)
            threading.Thread(target=helpMenu, daemon=True).start()

        else:
            db = ''
            query = ''
            valid_dbs = ["pubmed", "protein", "nuccore", "gene", "snp", "structure", "pmc", "genome", "taxonomy", "mesh", "sra"]
        
            if (len(args) < 2):
                db = "pubmed"
                query = args[0]
            else:
                db = args[0]
                query = args[1]

            if (db not in valid_dbs):
                err_msg = "Invalid db specified. Run NIHSearch -h for usage instructions."
                self.nvim.async_call(lambda: self.nvim.err_write(f"NIH Error: {err_msg}\n"))
                return
        
            self.nvim.out_write(f"Searching NIH database {db} for: {query}...\n")

            def task():
                try:
                    # Search for ID's
                    search_handle = Entrez.esearch(db="pubmed", term=query, retmax=100)
                    search_result = Entrez.read(search_handle)
                    ids = search_result.get("IdList", [])
                    search_handle.close()

                    if not ids:
                        self.nvim.err_write(f"No results found for '{query}'\n")
                        return

                    # Retrieve summaries using ID's
                    summary_handle = Entrez.esummary(db="pubmed", id=",".join(ids))
                    summaries = Entrez.read(summary_handle)
                    self.sum = summaries
                    summary_handle.close()

                    # UI
                    def updateUI():

                        queryBufHandle = self.nvim.api.create_buf(False, True)
                        self.SearchMapping(queryBufHandle)
                        queryBufHandle.options['buftype'] = 'nofile'
                        queryBufHandle.options['bufhidden'] = 'wipe'
                        queryBufHandle.options['filetype'] = 'markdown'
                    
                        lines = [ f"# NIH Database ({db}) Results For: {query}", "---", ""]

                        for paper in summaries:

                            title = paper.get('Title', 'N/A')
                            authors = paper.get('AuthorList', 'N/A')
                            datePublished = paper.get("PubDate", "N/A")
                            journal = paper.get("FullJournalName", "N/A")

                            lines.append(f"## {title}")
                            lines.append(f"**Date Published**: {datePublished}")
                            lines.append(f"**Journal**: {journal}")
                            lines.append(f"**Authors**: {', '.join(authors)}")
                            lines.append("**More**") # button to open floating window
                            lines.append("") 

                        queryBufHandle[:] = lines
                        queryBufHandle.options['modifiable'] = False

                        winWidth = self.nvim.options['columns']
                        winHeight = self.nvim.options['lines']

                        config = {
                            'relative': 'editor',
                            'row': int(winHeight / 4),
                            'col': int(winWidth / 4),
                            'width': int(winWidth / 2),
                            'height': int(winHeight / 2),
                            'border': 'rounded',
                            'anchor': 'NW', 
                            #'style': 'minimal', 
                            'focusable': True, 
                        }
                        self.nvim.command(':set linebreak')
                        self.nvim.command(':set breakindent')
                        queryWinHandle = self.nvim.api.open_win(queryBufHandle, True, config) # Keep this here, putting it within config dosent work
                        self.nvim.api.win_set_option(queryWinHandle, 'wrap', True)

                    self.nvim.async_call(updateUI)

                except Exception as e:
                    err_msg = str(e)
                    self.nvim.async_call(lambda: self.nvim.err_write(f"Error: {err_msg}\n"))

            threading.Thread(target=task, daemon=True).start()