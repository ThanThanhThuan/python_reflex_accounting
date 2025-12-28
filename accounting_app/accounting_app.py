import reflex as rx
from datetime import datetime
from typing import List
from sqlmodel import select, distinct

# --- DATABASE MODEL ---
class JournalEntry(rx.Model, table=True):
    """The General Ledger Table."""
    date: str
    description: str
    account: str
    category: str  # Asset, Liability, Equity, Revenue, Expense
    debit: float
    credit: float

class TrialBalanceRow(rx.Base):
    """Helper to store calculated rows for the UI."""
    account: str
    debit_balance: float
    credit_balance: float
    
    # NEW: Strings to hold the formatted text (e.g. "1,200.50")
    formatted_debit: str
    formatted_credit: str

# --- STATE MANAGEMENT ---
class LedgerState(rx.State):
    """State for the Ledger Page."""
    
    selected_account: str = "Cash"
    # Use quotes around "JournalEntry"
    ledger_entries: List[JournalEntry] = []  # Type hint for a list of JournalEntry objects- Or move the Model Part Upper
    available_accounts: List[str] = []

    def get_accounts(self):
        """Find all unique account names used in the database."""
        with rx.session() as session:
            # Get unique account names
            query = select(JournalEntry.account).distinct()
            self.available_accounts = session.exec(query).all()
            # If the current selection isn't in the list, default to the first one
            if self.available_accounts and self.selected_account not in self.available_accounts:
                self.selected_account = self.available_accounts[0]
            self.get_ledger_entries()
    @rx.var
    def account_balance(self) -> float:
        """Calculate Net Balance (Debit - Credit)."""
        debits = sum([e.debit for e in self.ledger_entries])
        credits = sum([e.credit for e in self.ledger_entries])
        return debits - credits
    @rx.var
    def formatted_balance(self) -> str:
        # This forces exactly 2 decimal places and adds commas (e.g., "1,200.50")
        return f"{self.account_balance:,.2f}"
    def set_account(self, account: str):
        """Change the view when user picks a dropdown item."""
        self.selected_account = account
        self.get_ledger_entries()
    def get_ledger_entries(self):
        """Fetch transactions ONLY for the selected account."""
        with rx.session() as session:
            query = (
                select(JournalEntry)
                .where(JournalEntry.account == self.selected_account)
                .order_by(JournalEntry.date.desc())
            )
            self.ledger_entries = session.exec(query).all()
  
class AccountingState(rx.State):
    """The app state."""
    
    # Form input variables
    description: str = ""
    amount: str = "0"
    debit_account: str = "Cash"
    credit_account: str = "Sales Revenue"
    
    # To store fetched entries
    entries: List[JournalEntry] = []

    def load_entries(self):
        """Fetch all entries from the database."""
        with rx.session() as session:
            # CORRECT: Use 'select' (from sqlmodel), not 'rx.select'
            query = select(JournalEntry).order_by(JournalEntry.id.desc())
            self.entries = session.exec(query).all()
    
    
    def add_transaction(self):
        """
        Double Entry Logic: 
        Takes one user input and creates TWO rows in the database.
        """
        try:
            amt = float(self.amount)
            if amt <= 0:
                return rx.window_alert("Amount must be positive.")
            
            current_date = datetime.now().strftime("%Y-%m-%d %H:%M")

            # 1. The Debit Entry
            debit_entry = JournalEntry(
                date=current_date,
                description=self.description,
                account=self.debit_account,
                category="Debit", 
                debit=amt,
                credit=0.0
            )

            # 2. The Credit Entry
            credit_entry = JournalEntry(
                date=current_date,
                description=self.description,
                account=self.credit_account,
                category="Credit",
                debit=0.0,
                credit=amt
            )

            with rx.session() as session:
                session.add(debit_entry)
                session.add(credit_entry)
                session.commit()
            
            # Reset form and reload
            self.description = ""
            self.amount = "0"
            self.load_entries()
            
        except ValueError:
            return rx.window_alert("Invalid Amount")

    @rx.var
    def total_balance(self) -> float:
        """Calculates strict Math check: Debits must equal Credits."""
        total_dr = sum([e.debit for e in self.entries])
        total_cr = sum([e.credit for e in self.entries])
        return total_dr - total_cr  # Should always be 0

class TrialBalanceState(rx.State):
    rows: List[TrialBalanceRow] = []
    total_dr: float = 0.0
    total_cr: float = 0.0

    def calculate_trial_balance(self):
        with rx.session() as session:
            # 1. Fetch ALL transactions
            all_entries = session.exec(select(JournalEntry)).all()
            
            # 2. Aggregate in Python (Dictionary: Account -> Net Amount)
            # Positive = Debit Balance, Negative = Credit Balance
            account_map = {}
            
            for entry in all_entries:
                if entry.account not in account_map:
                    account_map[entry.account] = 0.0
                
                # Add Debits, Subtract Credits
                account_map[entry.account] += (entry.debit - entry.credit)

            # 3. Convert to List of Rows
            new_rows = []
            t_dr = 0.0
            t_cr = 0.0

            for acc, net_bal in account_map.items():
                  # Skip accounts with 0 balance
                if abs(net_bal) < 0.01:
                    continue
                
                dr = net_bal if net_bal > 0 else 0.0
                cr = abs(net_bal) if net_bal < 0 else 0.0
                
                t_dr += dr
                t_cr += cr

                new_rows.append(
                    TrialBalanceRow(
                        account=acc, 
                        debit_balance=dr, 
                        credit_balance=cr,
                        # FORMATTING HAPPENS HERE NOW
                        formatted_debit=f"{dr:,.2f}",
                        formatted_credit=f"{cr:,.2f}"
                    )
                )
       
            self.rows = new_rows
            self.total_dr = t_dr
            self.total_cr = t_cr
    
    @rx.var
    def formatted_total_dr(self) -> str:
        return f"${self.total_dr:,.2f}"

    @rx.var
    def formatted_total_cr(self) -> str:
        return f"${self.total_cr:,.2f}"

    @rx.var
    def is_balanced(self) -> bool:
        # Check if difference is negligible
        return abs(self.total_dr - self.total_cr) < 0.01

# --- UI COMPONENTS ---

def stat_card(label, value, color):
    return rx.box(
        rx.text(label, font_size="sm", color="gray.400"),
        rx.text(value, font_size="2xl", font_weight="bold", color=color),
        padding="20px",
        background_color="#2D3748", # Dark gray
        border_radius="md",
        width="100%",
        box_shadow="lg"
    )

def entry_row(entry: JournalEntry):
    return rx.table.row(
        rx.table.cell(entry.date),
        rx.table.cell(entry.description, font_weight="bold"),
        rx.table.cell(rx.badge(entry.account, color_scheme="blue")),
        
        # FIX 1: Use rx.cond for logic
        # FIX 2: Remove ":,.2f" formatting (use simple string)
        rx.table.cell(
            f"${entry.debit}", 
            color=rx.cond(entry.debit > 0, "green", "gray")
        ),
        rx.table.cell(
            f"${entry.credit}", 
            color=rx.cond(entry.credit > 0, "red", "gray")
        ),
    )

def index():
    return rx.container(
        rx.vstack(
            rx.heading("Double Entry Ledger", color="white", margin_bottom="20px"),
            
            rx.link(
    rx.button("View Ledger ->", color_scheme="blue", variant="outline"),
    href="/ledger"
),
rx.link(
    rx.button("Trial Balance ->", color_scheme="purple", variant="outline"),
    href="/trial-balance"
),
            # 1. Transaction Form
            rx.box(
                rx.vstack(
                    rx.text("New Transaction", font_weight="bold", color="white"),
                    rx.input(placeholder="Description (e.g. Sold Widget)", on_change=AccountingState.set_description, value=AccountingState.description, background_color="white"),
                    rx.flex(
                        rx.vstack(
                            rx.text("Debit (Increase Asset/Exp)", color="gray.400", font_size="xs"),
                            rx.select(
                                ["Cash", "Equipment", "Supplies", "COGS Expense", "Rent Expense"],
                                on_change=AccountingState.set_debit_account,
                                background_color="white"
                            ),
                            width="48%"
                        ),
                        rx.spacer(),
                        rx.vstack(
                            rx.text("Credit (Increase Liab/Rev)", color="gray.400", font_size="xs"),
                            rx.select(
                                ["Sales Revenue", "Accounts Payable", "Owner Equity", "Bank Loan", "Cash"],
                                on_change=AccountingState.set_credit_account,
                                default_value="Sales Revenue",
                                background_color="white"
                            ),
                            width="48%"
                        ),
                        width="100%"
                    ),
                    rx.input(placeholder="Amount", on_change=AccountingState.set_amount, value=AccountingState.amount, type="number", background_color="white"),
                    rx.button("Post Transaction", on_click=AccountingState.add_transaction, width="100%", color_scheme="green"),
                    spacing="4",
                ),
                padding="20px",
                border="1px solid #444",
                border_radius="lg",
                background_color="#1A202C",
                width="100%",
            ),

            # 2. General Ledger Table
            rx.box(
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("Date"),
                            rx.table.column_header_cell("Description"),
                            rx.table.column_header_cell("Account"),
                            rx.table.column_header_cell("Debit"),
                            rx.table.column_header_cell("Credit"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(AccountingState.entries, entry_row)
                    ),
                    variant="surface",
                ),
                width="100%",
                margin_top="20px"
            ),
            
            # 3. Integrity Check
            rx.text(
                f"Ledger Integrity Check (Dr - Cr): {AccountingState.total_balance}", 
                color="gray.500", 
                font_size="xs",
                margin_top="10px"
            ),
            
            width="100%",
            max_width="800px",
            padding="20px"
        ),
        # Trigger load_entries when page opens
        on_mount=AccountingState.load_entries, 
        background_color="#111",
        min_height="100vh",
    )

def ledger_page():
    return rx.container(
        rx.vstack(
            # --- Navigation ---
            rx.hstack(
                rx.link("← Back to Journal", href="/", color="gray.400", font_size="sm"),
                rx.spacer(),
                rx.heading("Account Ledger", color="white"),
                width="100%",
                padding_bottom="20px"
            ),

            # --- Controls ---
            rx.box(
                rx.text("Select Account to View:", color="white", margin_bottom="5px"),
                rx.select(
                    LedgerState.available_accounts,
                    value=LedgerState.selected_account,
                    on_change=LedgerState.set_account,
                    background_color="white",
                    width="100%"
                ),
                padding="20px",
                background_color="#1A202C",
                border_radius="lg",
                width="100%",
                border="1px solid #444"
            ),

            # --- Summary Cards ---
            rx.hstack(
                # Balance Card
                rx.box(
                    rx.text("Net Balance", color="gray.400", font_size="sm"),
                    rx.text(
                        LedgerState.formatted_balance, 
                        font_size="3xl", 
                        font_weight="bold",
                        # Green if positive (Debit balance), Red if negative (Credit balance)
                        color=rx.cond(LedgerState.account_balance >= 0, "green.400", "red.400")
                    ),
                    padding="20px",
                    background_color="#2D3748",
                    border_radius="md",
                    width="100%"
                ),
                width="100%",
                padding_y="20px"
            ),

            # --- The Table ---
            rx.box(
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("Date"),
                            rx.table.column_header_cell("Description"),
                            rx.table.column_header_cell("Debit"),
                            rx.table.column_header_cell("Credit"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(LedgerState.ledger_entries, entry_row)
                    ),
                    variant="surface",
                ),
                width="100%",
            ),
            
            width="100%",
            max_width="800px",
            padding="20px"
        ),
        # Load data when page opens
        on_mount=LedgerState.get_accounts, 
        background_color="#111",
        min_height="100vh",
    )
# --- Helper to render a Trial Balance Row ---
def tb_row(row: TrialBalanceRow):
    return rx.table.row(
        rx.table.cell(row.account, font_weight="bold"),
        
        # DEBIT COLUMN
        rx.table.cell(
            f"${row.formatted_debit}",  # Use the pre-formatted string
            color=rx.cond(row.debit_balance > 0, "green", "gray") # Use float for logic
        ),
        
        # CREDIT COLUMN
        rx.table.cell(
            f"${row.formatted_credit}", # Use the pre-formatted string
            color=rx.cond(row.credit_balance > 0, "red", "gray") # Use float for logic
        ),
    )


def trial_balance_page():
    return rx.container(
        rx.vstack(
            # --- Navigation ---
            rx.hstack(
                rx.link("← Back to Journal", href="/", color="gray.400", font_size="sm"),
                rx.spacer(),
                rx.heading("Trial Balance", color="white"),
                width="100%",
                padding_bottom="20px"
            ),

            # --- Status Indicator ---
            rx.cond(
                TrialBalanceState.is_balanced,
                # SUCCESS CALLOUT
                rx.callout(
                    "Books are Balanced: Total Debits equal Total Credits.",
                    icon="check", 
                    color_scheme="green",
                    variant="soft",
                    width="100%"
                ),
                # ERROR CALLOUT
                rx.callout(
                    "UNBALANCED: There is a discrepancy in the books.",
                    icon="triangle_alert",
                    color_scheme="red",
                    variant="soft",
                    width="100%"
                ),
            ),

            # --- The Table ---
            rx.box(
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("Account Name"),
                            rx.table.column_header_cell("Debit"),
                            rx.table.column_header_cell("Credit"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(TrialBalanceState.rows, tb_row),
                        # Total Row
                        rx.table.row(
                            rx.table.cell("TOTALS", font_weight="bold", color="white"),
                            rx.table.cell(TrialBalanceState.formatted_total_dr, font_weight="bold", color="white", border_top="2px solid white"),
                            rx.table.cell(TrialBalanceState.formatted_total_cr, font_weight="bold", color="white", border_top="2px solid white"),
                            background_color="#2D3748"
                        )
                    ),
                    variant="surface",
                ),
                width="100%",
                margin_top="20px"
            ),
            
            width="100%",
            max_width="800px",
            padding="20px"
        ),
        on_mount=TrialBalanceState.calculate_trial_balance, 
        background_color="#111",
        min_height="100vh",
    )


app = rx.App(theme=rx.theme(appearance="dark"))
app.add_page(index, route="/")
app.add_page(ledger_page, route="/ledger") # <--- Add this
app.add_page(trial_balance_page, route="/trial-balance") # <--- Add this