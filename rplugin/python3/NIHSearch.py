import pynvim
import threading
from Bio import Entrez

@pynvim.plugin
class NIHSearch(object):
    def __init__(self, nvim):
        self.nvim = nvim
        self.sum = ""
        Entrez.email = "NIHSearch@nvim.com"

    @pynvim.command("DisplayPaperSummary", sync=True)
    def DisplayPaperSummary(self):
        try:
            def updateUI(): 
                valRow = [i for i in range(100) if (i == 8)]
                currBuf = self.nvim.api.get_current_buf()
                currWin = self.nvim.api.get_current_win()
                row, col = self.nvim.api.win_get_cursor(currWin)
                if (row in valRow):
                    ind = valRow.index(row)
                    currBuf.options['modifiable'] = True
                    currBuf[:] = ""

                    paper = self.sum[ind]
                    title = paper.get('Title', 'No Title')
                    authors = paper.get('AuthorList', 'Unknown')
                    datePublished = paper.get("PubDate", "Unknown")
                    journal = paper.get("FullJournalName", "Unknown")
                    #abstract = pull full abstract
                    comment = paper.get("Comment", "Unknown")
                    note = paper.get("Note", "Unknown")

                    lines = []
                    lines.append(f"## {title}")
                    lines.append(f"**Date Published**: {datePublished}")
                    lines.append(f"**Journal**: {journal}")
                    lines.append(f"**Authors**: {", ".join(authors)}")
                    lines.append("")
                    lines.append("**View Full Text**")
                    lines.append("")
                    lines.append("Abstract")
                    lines.append("---")
                    lines.append("Unknown") # abstract
                    lines.append("")
                    lines.append("Comment")
                    lines.append("---")
                    lines.append(comment)
                    lines.append("")
                    lines.append("Note")
                    lines.append("---")
                    lines.append(note)

                    currBuf[:] = lines
                    currBuf.options['modifiable'] = False
            self.nvim.async_call(updateUI)
        except Exception as e:
            err_msg = str(e)
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error: {err_msg}\n"))
    def SetupMapping(self, buf):
        opts = {'noremap': True, 'silent': True}
        buf.api.set_keymap('n', '<CR>', ':DisplayPaperSummary<CR>', opts)
        buf.api.set_keymap('n', '<LeftMouse>', '<LeftMouse>:DisplayPaperSummary<CR>', opts)

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

                    winWidth = self.nvim.api.win_get_width(0)
                    winHeight = self.nvim.api.win_get_height(0)

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
                        self.SetupMapping(queryBufHandle)
                        queryBufHandle.options['buftype'] = 'nofile'
                        queryBufHandle.options['bufhidden'] = 'wipe'
                        queryBufHandle.options['filetype'] = 'markdown'
                    
                        lines = [ f"# NIH Database ({db}) Results For: {query}", "---", ""]

                        for paper in summaries:

                            title = paper.get('Title', 'No Title')
                            authors = paper.get('AuthorList', 'Unknown')
                            datePublished = paper.get("PubDate", "Unknown")
                            journal = paper.get("FullJournalName", "Unknown")

                            lines.append(f"## {title}")
                            lines.append(f"**Date Published**: {datePublished}")
                            lines.append(f"**Journal**: {journal}")
                            lines.append(f"**Authors**: {", ".join(authors)}")
                            lines.append("**More**") # button to open floating window
                            lines.append("") # Spacer

                        queryBufHandle[:] = lines
                        queryBufHandle.options['modifiable'] = False

                        winWidth = self.nvim.api.win_get_width(0)
                        winHeight = self.nvim.api.win_get_height(0)

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

	    ## Improvements
            ## 1. DisplayPaperSummary() is editing the buffer when it should create a new buffer and inject it into the window. Window should be edited, not the buffer
            ## 2. Get rid of the self.sum property and pass the array as an arg to DisplayPaperSummary()
            ## 3. Create an AbstractParser function. Use in DisplayPaperSummary() to display a papers abstract after using Entrez.efetch(db=arg, id=arg, retmode=arg)
            ## 4. Implement loading screen while AbstractParser runs as Entrez.efetch() can take a few seconds
	    ## 5. Fix imporper valRow implementation in DisplayPaperSummary()

	    ## On **View Full Text** Implementation
	    ## 1. PMC papers can be downloaded in full as XML or PDF's. Try to parse the XML and display this in a new buffer.
	    ## 2. Many other papers will be pdf only of paywalled + pdf. The easy option is to just add a link here that just opens in the users browser.
	    	## Terminal/Vim only solutions include
		## 1. Download the PDF's temporarily (if not paywalled) and use termpdf.py to draw the pdf onto a new terminal window.
		## 2. Using pdftotext to get the PDF's text and load that into a buffer, will lose out on images tho :( 
		## 3. Using telescopre-media-files.nvim to load the PDF into a floating window and prompting the user if they would like the paper to load in a new window.
		## This last option renders the full PDF and dosent require losing out on the graphs an images but it does come with the dependecny overhead
		## of the user now needing a compatible terminal, image.nvim, and Magick. Implementation would be quite easy as the plugins do most of the work. 
 

