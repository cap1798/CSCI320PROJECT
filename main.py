import re
import psycopg
from sshtunnel import SSHTunnelForwarder
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import hashlib
import os
import datetime
import random


# Hashes a password with a random salt.
def hash_password(password):
    salt = os.urandom(16)
    hashed_pass = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{hashed_pass.hex()}"


# Checks a provided password against a stored salt:hash string.
def check_password(stored_password, provided_password):
    try:
        salt_hex, hash_hex = stored_password.split(':')
        salt = bytes.fromhex(salt_hex)
        stored_hash = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    hashed_pass = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
    return hashed_pass == stored_hash


# Converts total minutes to 'HH:MM' format.
def format_duration(minutes):
    if minutes is None:
        return "00:00"
    try:
        total_minutes = int(minutes)
        hours = total_minutes // 60
        mins = total_minutes % 60
        return f"{hours:02}:{mins:02}"
    except (ValueError, TypeError):
        return "00:00"


# The main Tkinter application class that manages all frames and the DB connection.
class App(tk.Tk):
    # Initializes the main application window and database connection.
    def __init__(self, *args, **kwargs):
        tk.Tk.__init__(self, *args, **kwargs)
        self.title("Video Game Tracker")
        self.geometry("1024x700")

        try:
            with open('config.txt', 'r') as f:
                lines = f.readlines()
                self.username = lines[0].strip()
                self.password = lines[1].strip()
                self.dbName = lines[2].strip()
        except (IOError, IndexError):
            messagebox.showerror("Config Error",
                                 "Could not read config.txt.\n"
                                 "Make sure it exists and has 3 lines:\n"
                                 "username\npassword\ndbname")
            self.destroy()
            return

        self.conn = None
        self.curs = None
        self.server = None

        self.current_user_id = None

        if not self.connect_db():
            self.destroy()
            return

        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for F in (LoginFrame, RegisterFrame, MainAppFrame):
            page_name = F.__name__
            frame = F(parent=container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("LoginFrame")

    # Establishes the SSH tunnel and database connection.
    def connect_db(self):
        try:
            self.server = SSHTunnelForwarder(
                ('starbug.cs.rit.edu', 22),
                ssh_username=self.username,
                ssh_password=self.password,
                remote_bind_address=('127.0.0.1', 5432)
            )
            self.server.start()
            print("SSH tunnel established")

            params = {
                'dbname': self.dbName,
                'user': self.username,
                'password': self.password,
                'host': '127.0.0.1',
                'port': self.server.local_bind_port
            }
            self.conn = psycopg.connect(**params)
            self.curs = self.conn.cursor()
            print("Database connection established")

            # OPTIMIZATION: Apply indexes immediately after connection
            self.optimize_database()

            return True
        except Exception as e:
            messagebox.showerror("Connection Failed", f"Could not connect to database:\n{e}")
            return False

    def optimize_database(self):
        try:
            print("Applying performance indexes...")
            indexes = [
                # Speed up Login and Registration
                "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",

                # Speed up Collection Loading (Filtering by User)
                "CREATE INDEX IF NOT EXISTS idx_collection_userid ON collection(userid)",

                # Speed up Joins for Collections and Plays
                "CREATE INDEX IF NOT EXISTS idx_plays_userid_gameid ON plays(userid, gameid)",
                "CREATE INDEX IF NOT EXISTS idx_collectiongame_col_game ON collectiongame(collectionid, gameid)",

                # Speed up 'Popular in Last 90 Days' (Time filtering)
                "CREATE INDEX IF NOT EXISTS idx_plays_date ON plays(playdatetime)",

                # Speed up Search Joins (Foreign Keys are not indexed by default in PG)
                "CREATE INDEX IF NOT EXISTS idx_gameplatform_gameid ON gameplatform(gameid)",
                "CREATE INDEX IF NOT EXISTS idx_gamedeveloper_gameid ON gamedeveloper(gameid)",
                "CREATE INDEX IF NOT EXISTS idx_gamepublisher_gameid ON gamepublisher(gameid)",
                "CREATE INDEX IF NOT EXISTS idx_gamegenre_gameid ON gamegenre(gameid)",

                # Speed up Social Features
                "CREATE INDEX IF NOT EXISTS idx_follows_follower ON follows(followerid)",
                "CREATE INDEX IF NOT EXISTS idx_follows_followed ON follows(followedid)",

                # Speed up New Releases (Date Sorting/Filtering)
                "CREATE INDEX IF NOT EXISTS idx_gameplatform_release ON gameplatform(releasedate)"
            ]

            for idx_sql in indexes:
                self.curs.execute(idx_sql)
            self.conn.commit()
            print("Indexes applied successfully.")

        except Exception as e:
            print(f"Index optimization warning: {e}")
            self.conn.rollback()

    # Raises the specified frame to the top.
    def show_frame(self, page_name):
        frame = self.frames[page_name]
        if page_name == "MainAppFrame":
            frame.refresh_data()
        frame.tkraise()

    # Handles the window close event, closing the DB and SSH tunnel.
    def on_closing(self):
        if self.conn:
            self.conn.close()
            print("Database connection closed")
        if self.server:
            self.server.stop()
            print("SSH tunnel closed")
        self.destroy()


# The frame for the user login page.
class LoginFrame(tk.Frame):
    # Initializes the login UI components.
    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent)
        self.controller = controller

        frame = ttk.Frame(self, padding="30")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(frame, text="Login", font=("Arial", 24)).pack(pady=20)

        ttk.Label(frame, text="Username").pack(pady=(0, 5))
        self.username_entry = ttk.Entry(frame, width=30)
        self.username_entry.pack()

        ttk.Label(frame, text="Password").pack(pady=(10, 5))
        self.password_entry = ttk.Entry(frame, show="*", width=30)
        self.password_entry.pack()

        ttk.Button(frame, text="Login", command=self.login).pack(pady=20, ipadx=10)
        ttk.Button(frame, text="Create Account", command=lambda: controller.show_frame("RegisterFrame")).pack()

    # Handles the login attempt.
    def login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()

        if not username or not password:
            messagebox.showerror("Error", "Please enter both username and password.")
            return

        try:
            self.controller.curs.execute(
                'SELECT userid, password FROM users WHERE username = %s',
                (username,)
            )
            user_data = self.controller.curs.fetchone()

            if user_data:
                user_id, stored_password = user_data

                if check_password(stored_password, password):
                    self.controller.curs.execute(
                        'UPDATE users SET lastaccessdate = %s WHERE userid = %s',
                        (datetime.datetime.now(), user_id)
                    )
                    self.controller.conn.commit()

                    self.controller.current_user_id = user_id
                    messagebox.showinfo("Success", f"Welcome, {username}!")
                    self.password_entry.delete(0, 'end')
                    self.controller.show_frame("MainAppFrame")
                else:
                    messagebox.showerror("Error", "Invalid username or password.")
            else:
                messagebox.showerror("Error", "Invalid username or password.")

        except Exception as e:
            messagebox.showerror("Database Error", f"An error occurred: {e}")
            self.controller.conn.rollback()


# The frame for the new user registration page.
class RegisterFrame(tk.Frame):
    # Initializes the registration UI components.
    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent)
        self.controller = controller

        frame = ttk.Frame(self, padding="30")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(frame, text="Create Account", font=("Arial", 24)).grid(row=0, column=0, columnspan=2, pady=20)

        ttk.Label(frame, text="First Name:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.fname_entry = ttk.Entry(frame, width=30)
        self.fname_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Last Name:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        self.lname_entry = ttk.Entry(frame, width=30)
        self.lname_entry.grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Email:").grid(row=3, column=0, sticky="e", padx=5, pady=5)
        self.email_entry = ttk.Entry(frame, width=30)
        self.email_entry.grid(row=3, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Username:").grid(row=4, column=0, sticky="e", padx=5, pady=5)
        self.username_entry = ttk.Entry(frame, width=30)
        self.username_entry.grid(row=4, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Password:").grid(row=5, column=0, sticky="e", padx=5, pady=5)
        self.password_entry = ttk.Entry(frame, show="*", width=30)
        self.password_entry.grid(row=5, column=1, padx=5, pady=5)

        ttk.Button(frame, text="Register", command=self.register).grid(row=6, column=0, columnspan=2, pady=20)
        ttk.Button(frame, text="Back to Login", command=lambda: controller.show_frame("LoginFrame")).grid(row=7,
                                                                                                          column=0,
                                                                                                          columnspan=2)

    # Handles the new user registration.
    def register(self):
        fname = self.fname_entry.get()
        lname = self.lname_entry.get()
        email = self.email_entry.get().strip().lower()
        username = self.username_entry.get().strip().lower()
        password = self.password_entry.get()

        if not all([fname, lname, email, username, password]):
            messagebox.showerror("Error", "Please fill in all fields.")
            return

        # Validate email format
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            messagebox.showerror("Error", "Invalid email format.")
            return

        hashed_password = hash_password(password)

        try:
            # Explicitly check if username or email already exists
            self.controller.curs.execute(
                "SELECT username, email FROM users WHERE username = %s OR email = %s",
                (username, email)
            )
            existing_user = self.controller.curs.fetchone()

            if existing_user:
                existing_username, existing_email = existing_user
                if existing_username == username:
                    messagebox.showerror("Error", "Username already exists.")
                elif existing_email == email:
                    messagebox.showerror("Error", "Email already exists.")
                return

            # Reset sequence if necessary (to avoid "Key (userid) already exists" error)
            self.controller.curs.execute(
                "SELECT setval('users_userid_seq', (SELECT MAX(userid) FROM users));"
            )

            # If no duplicates, proceed with the insertion
            self.controller.curs.execute(
                """
                INSERT INTO users (firstname, lastname, email, username, password, creationdate)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (fname, lname, email, username, hashed_password, datetime.datetime.now())
            )
            self.controller.conn.commit()
            messagebox.showinfo("Success", "Account created successfully! Please log in.")
            for entry in [self.fname_entry, self.lname_entry, self.email_entry, self.username_entry,
                          self.password_entry]:
                entry.delete(0, 'end')
            self.controller.show_frame("LoginFrame")

        except psycopg.Error as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"An unexpected error occurred: {e}")


# The main application frame, containing the tabbed interface.
class MainAppFrame(tk.Frame):
    # Initializes the main app UI, including the notebook for tabs.
    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent)
        self.controller = controller

        top_bar = ttk.Frame(self)
        top_bar.pack(side="top", fill="x", pady=5, padx=10)

        self.welcome_label = ttk.Label(top_bar, text="", font=("Arial", 14))
        self.welcome_label.pack(side="left")

        logout_button = ttk.Button(top_bar, text="Logout", command=self.logout)
        logout_button.pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(side="top", fill="x", padx=10)

        self.notebook = ttk.Notebook(self)

        self.collections_frame = CollectionsFrame(self.notebook, self.controller)
        self.search_frame = SearchFrame(self.notebook, self.controller)
        self.social_frame = SocialFrame(self.notebook, self.controller)
        self.profile_frame = ProfileFrame(self.notebook, self.controller)
        self.popular_frame = PopularFrame(self.notebook, self.controller)

        self.notebook.add(self.collections_frame, text="My Collections")
        self.notebook.add(self.search_frame, text="Search Games")
        self.notebook.add(self.social_frame, text="Social")
        self.notebook.add(self.profile_frame, text="My Profile")
        self.notebook.add(self.popular_frame, text="Popular & Recommended")

        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        # Bind tab selection event to refresh data
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    # Handles tab changes to refresh data.
    def on_tab_changed(self, event):
        selected_tab = event.widget.select()
        tab_text = event.widget.tab(selected_tab, "text")

        if tab_text == "My Profile":
            self.profile_frame.load_profile()
        elif tab_text == "Popular & Recommended":
            self.popular_frame.load_data()
        elif tab_text == "Social":
            self.social_frame.load_following()

    # Handles user logout.
    def logout(self):
        self.controller.current_user_id = None
        self.welcome_label.config(text="")
        self.controller.show_frame("LoginFrame")

    # Refreshes data in all tabs when the main frame is shown.
    def refresh_data(self):
        if self.controller.current_user_id:
            try:
                self.controller.curs.execute(
                    'SELECT firstname FROM users WHERE userid = %s',
                    (self.controller.current_user_id,)
                )
                user_name = self.controller.curs.fetchone()[0]
                self.welcome_label.config(text=f"Welcome, {user_name}!")
            except Exception as e:
                self.welcome_label.config(text="Welcome!")
                print(f"Error fetching user name: {e}")

            self.collections_frame.load_collections()
            self.social_frame.load_following()
            self.profile_frame.load_profile()
            self.popular_frame.load_data()


# The frame for the "My Collections" tab.
class CollectionsFrame(ttk.Frame):
    # Initializes the collection management UI.
    def __init__(self, parent, controller):
        ttk.Frame.__init__(self, parent, padding="10")
        self.controller = controller

        list_frame = ttk.Frame(self)
        list_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        cols = ("Name", "Game Count", "Total Playtime")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings")

        self.tree.heading("Name", text="Collection Name")
        self.tree.heading("Game Count", text="Games")
        self.tree.heading("Total Playtime", text="Playtime (HH:MM)")

        self.tree.column("Name", width=250)
        self.tree.column("Game Count", width=50, anchor="center")
        self.tree.column("Total Playtime", width=120, anchor="center")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        controls_frame = ttk.Frame(self, padding="10")
        controls_frame.pack(side="right", fill="y")

        ttk.Label(controls_frame, text="Manage Collections", font=("Arial", 16)).pack(pady=10)

        ttk.Label(controls_frame, text="New Collection Name:").pack(pady=(10, 5))
        self.new_collection_entry = ttk.Entry(controls_frame, width=30)
        self.new_collection_entry.pack()

        ttk.Button(controls_frame, text="Create Collection", command=self.create_collection).pack(pady=10)

        ttk.Separator(controls_frame, orient="horizontal").pack(fill="x", pady=10)

        ttk.Button(controls_frame, text="View/Manage Selected", command=self.view_collection_details).pack(pady=5,
                                                                                                           fill="x")
        ttk.Button(controls_frame, text="Play Random from Selected", command=self.play_random).pack(pady=5, fill="x")
        ttk.Button(controls_frame, text="Rename Selected", command=self.rename_collection).pack(pady=5, fill="x")
        ttk.Button(controls_frame, text="Delete Selected", command=self.delete_collection).pack(pady=5, fill="x")

        self.tree['displaycolumns'] = ("Name", "Game Count", "Total Playtime")
        self.tree["columns"] = ("CollectionID", "Name", "Game Count", "Total Playtime")
        self.tree.column("CollectionID", width=0, stretch=tk.NO)

    # Fetches and displays all collections for the current user.
    def load_collections(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not self.controller.current_user_id:
            return

        try:
            sql = """
                SELECT 
                    c.collectionid,
                    c.name, 
                    COUNT(DISTINCT cg.gameid) AS gamecount,
                    COALESCE(SUM(p.duration), 0) AS totaldurationminutes
                FROM 
                    collection c
                LEFT JOIN 
                    collectiongame cg ON c.collectionid = cg.collectionid
                LEFT JOIN 
                    plays p ON cg.gameid = p.gameid AND c.userid = p.userid
                WHERE 
                    c.userid = %s
                GROUP BY 
                    c.collectionid, c.name
                ORDER BY 
                    c.name ASC;
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id,))

            for row in self.controller.curs.fetchall():
                collection_id, name, game_count, total_minutes = row
                playtime_str = format_duration(total_minutes)
                self.tree.insert("", "end", values=(collection_id, name, game_count, playtime_str))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load collections: {e}")
            self.controller.conn.rollback()

    # Creates a new collection for the user.
    def create_collection(self):
        new_name = self.new_collection_entry.get()
        if not new_name:
            messagebox.showwarning("Warning", "Please enter a name for the new collection.")
            return

        try:
            # Reset sequence for collectionid to avoid "Key (collectionid) already exists" error
            self.controller.curs.execute(
                "SELECT setval('collection_collectionid_seq', (SELECT MAX(collectionid) FROM collection));"
            )

            # Insert the new collection
            sql = 'INSERT INTO collection (userid, name) VALUES (%s, %s)'
            self.controller.curs.execute(sql, (self.controller.current_user_id, new_name))
            self.controller.conn.commit()

            self.new_collection_entry.delete(0, 'end')
            self.load_collections()
            # Refresh profile if it exists
            if hasattr(self.controller.frames["MainAppFrame"], 'profile_frame'):
                self.controller.frames["MainAppFrame"].profile_frame.load_profile()

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", "A collection with this name already exists.")
            else:
                messagebox.showerror("Database Error", f"Failed to create collection: {e}")

    # Helper to get the CollectionID and Name of the selected item.
    def get_selected_collection(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a collection from the list first.")
            return None, None

        item_data = self.tree.item(selected_item)
        collection_id = item_data['values'][0]
        collection_name = item_data['values'][1]
        return collection_id, collection_name

    # Renames the selected collection.
    def rename_collection(self):
        collection_id, current_name = self.get_selected_collection()
        if not collection_id:
            return

        new_name = simpledialog.askstring("Rename Collection",
                                          "Enter new name:",
                                          initialvalue=current_name)

        if not new_name:
            return

        try:
            sql = 'UPDATE collection SET name = %s WHERE collectionid = %s AND userid = %s'
            self.controller.curs.execute(sql, (new_name, collection_id, self.controller.current_user_id))
            self.controller.conn.commit()
            self.load_collections()

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", "A collection with this name already exists.")
            else:
                messagebox.showerror("Database Error", f"Failed to rename collection: {e}")

    # Deletes the selected collection after confirmation.
    def delete_collection(self):
        collection_id, collection_name = self.get_selected_collection()
        if not collection_id:
            return

        if not messagebox.askyesno("Confirm Delete",
                                   f"Are you sure you want to delete the collection '{collection_name}'?\n"
                                   "All games in this collection will be removed from it (but not deleted from the system)."):
            return

        try:
            sql_games = 'DELETE FROM collectiongame WHERE collectionid = %s'
            self.controller.curs.execute(sql_games, (collection_id,))

            sql_coll = 'DELETE FROM collection WHERE collectionid = %s AND userid = %s'
            self.controller.curs.execute(sql_coll, (collection_id, self.controller.current_user_id))

            self.controller.conn.commit()
            self.load_collections()
            # Refresh profile if it exists
            if hasattr(self.controller.frames["MainAppFrame"], 'profile_frame'):
                self.controller.frames["MainAppFrame"].profile_frame.load_profile()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to delete collection: {e}")

    # Logs a play session for a random game from the selected collection.
    def play_random(self):
        collection_id, collection_name = self.get_selected_collection()
        if not collection_id:
            return

        try:
            # Fetch all games from the collection
            sql = """
                SELECT gameid FROM collectiongame 
                WHERE collectionid = %s
            """
            self.controller.curs.execute(sql, (collection_id,))
            games = self.controller.curs.fetchall()

            if not games:
                messagebox.showinfo("Empty Collection", f"The collection '{collection_name}' has no games in it.")
                return

            # Use Python's random to select a game
            game_id = random.choice(games)[0]

            duration = simpledialog.askinteger("Log Play Session", "How many minutes did you play?", minvalue=1)
            if not duration:
                return

            sql_play = """
                INSERT INTO plays (userid, gameid, playdatetime, duration)
                VALUES (%s, %s, %s, %s)
            """
            self.controller.curs.execute(sql_play,
                                         (self.controller.current_user_id, game_id, datetime.datetime.now(), duration))
            self.controller.conn.commit()

            messagebox.showinfo("Success", f"Logged {duration} minutes for a random game from '{collection_name}'.")
            self.load_collections()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to play random game: {e}")

    # Opens a new window to view/manage games within a collection.
    def view_collection_details(self):
        collection_id, collection_name = self.get_selected_collection()
        if not collection_id:
            return

        CollectionDetailWindow(self, collection_id, collection_name, self.controller)


# A new Toplevel window for managing games in a single collection.
class CollectionDetailWindow(tk.Toplevel):
    # Initializes the collection detail UI.
    def __init__(self, parent_frame, collection_id, collection_name, controller):
        tk.Toplevel.__init__(self, parent_frame)
        self.transient(parent_frame)
        self.grab_set()

        self.controller = controller
        self.collection_id = collection_id
        self.parent_frame = parent_frame

        self.title(f"Managing: {collection_name}")
        self.geometry("600x400")

        list_frame = ttk.Frame(self, padding="10")
        list_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        cols = ("Title", "ESRB")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings")
        self.tree.heading("Title", text="Game Title")
        self.tree.heading("ESRB", text="Age Rating")
        self.tree.column("ESRB", width=80, anchor="center")

        self.tree['displaycolumns'] = ("Title", "ESRB")
        self.tree["columns"] = ("GameID", "Title", "ESRB")
        self.tree.column("GameID", width=0, stretch=tk.NO)

        self.tree.pack(fill="both", expand=True)

        controls_frame = ttk.Frame(self, padding="10")
        controls_frame.pack(side="right", fill="y")

        ttk.Button(controls_frame, text="Remove Selected Game", command=self.remove_game).pack(pady=10)
        ttk.Button(controls_frame, text="Close", command=self.close).pack(pady=5)

        self.load_games()

    # Loads games for the *specific* collection.
    def load_games(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            sql = """
                SELECT g.gameid, g.title, g.esrb_rating
                FROM videogame g
                JOIN collectiongame cg ON g.gameid = cg.gameid
                WHERE cg.collectionid = %s
                ORDER BY g.title ASC;
            """
            self.controller.curs.execute(sql, (self.collection_id,))

            for row in self.controller.curs.fetchall():
                self.tree.insert("", "end", values=row)

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load games in collection: {e}", parent=self)
            self.controller.conn.rollback()

    # Removes a selected game from this collection.
    def remove_game(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a game to remove.", parent=self)
            return

        game_id, game_title, _ = self.tree.item(selected_item)['values']

        if not messagebox.askyesno("Confirm", f"Remove '{game_title}' from this collection?", parent=self):
            return

        try:
            sql = 'DELETE FROM collectiongame WHERE collectionid = %s AND gameid = %s'
            self.controller.curs.execute(sql, (self.collection_id, game_id))
            self.controller.conn.commit()

            self.load_games()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to remove game: {e}", parent=self)

    # Closes the detail window and refreshes the main collections list.
    def close(self):
        self.parent_frame.load_collections()
        self.destroy()


# The frame for the "Search Games" tab.
class SearchFrame(ttk.Frame):
    # Initializes the game search UI.
    def __init__(self, parent, controller):
        ttk.Frame.__init__(self, parent, padding="10")
        self.controller = controller
        self.search_results_data = []

        filter_frame = ttk.Frame(self)
        filter_frame.pack(side="top", fill="x", pady=(0, 10))

        ttk.Label(filter_frame, text="Game Title:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.title_entry = ttk.Entry(filter_frame, width=25)
        self.title_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="Developer:").grid(row=0, column=2, padx=5, pady=5, sticky="e")
        self.dev_entry = ttk.Entry(filter_frame, width=25)
        self.dev_entry.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="Platform:").grid(row=0, column=4, padx=5, pady=5, sticky="e")
        self.platform_entry = ttk.Entry(filter_frame, width=25)
        self.platform_entry.grid(row=0, column=5, padx=5, pady=5)

        ttk.Label(filter_frame, text="Genre:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.genre_entry = ttk.Entry(filter_frame, width=25)
        self.genre_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="Publisher:").grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.pub_entry = ttk.Entry(filter_frame, width=25)
        self.pub_entry.grid(row=1, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="Release Year:").grid(row=1, column=4, padx=5, pady=5, sticky="e")
        self.year_entry = ttk.Entry(filter_frame, width=10)
        self.year_entry.grid(row=1, column=5, padx=5, pady=5, sticky="w")

        ttk.Label(filter_frame, text="Price (Max):").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.price_entry = ttk.Entry(filter_frame, width=10)
        self.price_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        search_button = ttk.Button(filter_frame, text="Search", command=self.search_games)
        search_button.grid(row=0, column=6, rowspan=3, padx=20, ipady=10, sticky="ns")
        filter_frame.grid_columnconfigure(6, weight=1)

        results_frame = ttk.Frame(self)
        results_frame.pack(fill="both", expand=True, pady=(10, 0))

        # Define all columns including hidden ones
        all_cols = ("GameID", "Title", "Year", "Price", "Platforms", "Developers", "Publisher",
                    "My PlaytimeNum", "My Playtime", "Age Rating", "My RatingNum", "My Rating", "Genres")

        self.tree = ttk.Treeview(results_frame, columns=all_cols, show="headings")

        # Set up visible columns
        visible_cols = ("Title", "Year", "Price", "Platforms", "Developers", "Publisher",
                        "My Playtime", "Age Rating", "My Rating")

        self.tree['displaycolumns'] = visible_cols

        # Hide the non-display columns
        self.tree.column("GameID", width=0, stretch=tk.NO)
        self.tree.column("My PlaytimeNum", width=0, stretch=tk.NO)
        self.tree.column("My RatingNum", width=0, stretch=tk.NO)
        self.tree.column("Genres", width=0, stretch=tk.NO)

        # Set up headings for visible columns with sort commands
        for col in visible_cols:
            self.tree.heading(col, text=col, command=lambda _col=col: self.sort_column(_col, False))

        # Set column widths for visible columns
        self.tree.column("Title", width=200)
        self.tree.column("Year", width=50, anchor="center")
        self.tree.column("Price", width=50, anchor="center")
        self.tree.column("Platforms", width=110)
        self.tree.column("Developers", width=110)
        self.tree.column("Publisher", width=110)
        self.tree.column("My Playtime", width=80, anchor="center")
        self.tree.column("Age Rating", width=80, anchor="center")
        self.tree.column("My Rating", width=80, anchor="center")

        scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        action_frame = ttk.Frame(self)
        action_frame.pack(side="bottom", fill="x", pady=(10, 0))

        # Add dropdown or buttons for sorting options
        sort_frame = ttk.Frame(self)
        sort_frame.pack(side="top", fill="x", pady=(5, 10))

        # Dropdown for sorting options
        sort_label = ttk.Label(sort_frame, text="Sort by:")
        sort_label.pack(side="left", padx=5)

        self.sort_var = tk.StringVar(value="Title ASC")
        sort_dropdown = ttk.OptionMenu(
            sort_frame, self.sort_var,
            "Title ASC", "Title DESC", "Price ASC", "Price DESC",
            "Genre ASC", "Genre DESC", "Year ASC", "Year DESC"
        )
        sort_dropdown.pack(side="left", padx=5)
        # Apply sorting button
        sort_button = ttk.Button(sort_frame, text="Apply Sort", command=self.apply_sort)
        sort_button.pack(side="left", padx=5)

        ttk.Button(action_frame, text="Add Selected to Collection...", command=self.add_to_collection).pack(side="left",
                                                                                                            padx=2)
        ttk.Button(action_frame, text="Rate Selected Game...", command=self.rate_game).pack(side="left", padx=2)
        ttk.Button(action_frame, text="Play Selected Game...", command=self.play_game).pack(side="left", padx=2)

    # Builds and executes a dynamic search query based on all filters.
    def search_games(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.search_results_data = []

        try:
            base_sql = """
                SELECT 
                    g.gameid, 
                    g.title,
                    g.esrb_rating,
                    STRING_AGG(DISTINCT p.name, ', ') AS platforms,
                    STRING_AGG(DISTINCT dev.name, ', ') AS developers,
                    STRING_AGG(DISTINCT pub.name, ', ') AS publishers,
                    STRING_AGG(DISTINCT gen.name, ', ') AS genres,
                    COALESCE(SUM(pl.duration), 0) AS totalplaytime,
                    pu.starrating,
                    MIN(EXTRACT(YEAR FROM gp.releasedate)) AS releaseyear,
                    MIN(gp.price) AS minprice,
                    MIN(gp.releasedate) AS minreleasedate
                FROM 
                    videogame g
                LEFT JOIN gameplatform gp ON g.gameid = gp.gameid
                LEFT JOIN platform p ON gp.platformid = p.platformid
                LEFT JOIN gamedeveloper gd ON g.gameid = gd.gameid
                LEFT JOIN company dev ON gd.companyid = dev.companyid
                LEFT JOIN gamepublisher gpub ON g.gameid = gpub.gameid
                LEFT JOIN company pub ON gpub.companyid = pub.companyid
                LEFT JOIN gamegenre gg ON g.gameid = gg.gameid
                LEFT JOIN genres gen ON gg.genreid = gen.genreid
                LEFT JOIN plays pl ON g.gameid = pl.gameid AND pl.userid = %s
                LEFT JOIN purchases pu ON g.gameid = pu.gameid AND pu.userid = %s
                WHERE 1=1
            """

            where_clauses = []
            params = [self.controller.current_user_id, self.controller.current_user_id]

            if self.title_entry.get():
                where_clauses.append('g.title ILIKE %s')
                params.append(f"%{self.title_entry.get()}%")

            if self.dev_entry.get():
                where_clauses.append('dev.name ILIKE %s')
                params.append(f"%{self.dev_entry.get()}%")

            if self.pub_entry.get():
                where_clauses.append('pub.name ILIKE %s')
                params.append(f"%{self.pub_entry.get()}%")

            if self.genre_entry.get():
                where_clauses.append('gen.name ILIKE %s')
                params.append(f"%{self.genre_entry.get()}%")

            if self.platform_entry.get():
                where_clauses.append('p.name ILIKE %s')
                params.append(f"%{self.platform_entry.get()}%")

            if self.year_entry.get():
                try:
                    year = int(self.year_entry.get())
                    where_clauses.append('EXTRACT(YEAR FROM gp.releasedate) = %s')
                    params.append(year)
                except ValueError:
                    messagebox.showwarning("Warning", "Invalid Release Year. Must be a number. Year filter ignored.")

            if self.price_entry.get():
                try:
                    price = float(self.price_entry.get())
                    where_clauses.append('gp.price <= %s')
                    params.append(price)
                except ValueError:
                    messagebox.showwarning("Warning", "Invalid Price. Must be a number. Price filter ignored.")

            if where_clauses:
                base_sql += " AND " + " AND ".join(where_clauses)

            base_sql += """
                GROUP BY g.gameid, g.title, g.esrb_rating, pu.starrating
                ORDER BY g.title ASC, minreleasedate ASC;
            """

            self.controller.curs.execute(base_sql, params)

            for row in self.controller.curs.fetchall():
                # Unpack in the correct order matching the SQL SELECT
                (game_id, title, esrb, platforms, devs, pubs, genres,
                 playtime_num, rating_num, year, price, _) = row

                playtime_str = format_duration(playtime_num)
                rating_str = f"{rating_num} ★" if rating_num else "N/A"
                year_str = int(year) if year else "N/A"
                price_str = f"${price:.2f}" if price is not None else "N/A"

                self.search_results_data.append(row)

                self.tree.insert("", "end", values=(
                    game_id, title, year_str, price_str, platforms, devs, pubs,
                    playtime_num, playtime_str, esrb, rating_num, rating_str, genres
                ))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to search games: {e}")
            self.controller.conn.rollback()

    # Sorts the treeview by a column without re-querying.
    def sort_column(self, col, reverse):
        try:
            if col == "Price":
                data = []
                for item in self.tree.get_children(''):
                    price_val = self.tree.set(item, col)
                    if price_val == "N/A":  # Handle missing values
                        data.append((-1.0, item))
                    else:
                        price_val = price_val.replace("$", "")  # Remove dollar sign
                        data.append((float(price_val), item))  # Convert to float
            elif col == "My Playtime":
                data = [(float(self.tree.set(item, "My PlaytimeNum")), item) for item in self.tree.get_children('')]
            elif col == "My Rating":
                data = [(float(self.tree.set(item, "My RatingNum") or -1), item) for item in self.tree.get_children('')]
            elif col == "Year":
                data = [(float(self.tree.set(item, col) if self.tree.set(item, col) != "N/A" else 0), item) for item in
                        self.tree.get_children('')]
            elif col == "Genres":  # Sorting logic for Genres (hidden column)
                data = [(self.tree.set(item, col).lower() if self.tree.set(item, col) else "", item) for item in
                        self.tree.get_children('')]
            else:
                data = [(self.tree.set(item, col).lower(), item) for item in self.tree.get_children('')]
        except Exception as e:
            print(f"Sort error: {e}")
            return

        # Sort data and update TreeView
        data.sort(reverse=reverse)
        for index, (val, item) in enumerate(data):
            self.tree.move(item, '', index)

        # Update column heading to toggle sort order
        self.tree.heading(col, command=lambda: self.sort_column(col, not reverse))

    # Helper to get the GameID and Title of the selected item.
    def get_selected_game(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a game from the search results.")
            return None, None

        item_data = self.tree.item(selected_item)
        game_id = item_data['values'][0]
        game_title = item_data['values'][1]
        return game_id, game_title

    def apply_sort(self):
        # Get the currently selected sorting option from the dropdown
        sort_option = self.sort_var.get()

        # Map dropdown options to Treeview column names and sort directions
        col_map = {
            "Title ASC": ("Title", False),
            "Title DESC": ("Title", True),
            "Price ASC": ("Price", False),
            "Price DESC": ("Price", True),
            "Genre ASC": ("Genres", False),
            "Genre DESC": ("Genres", True),
            "Year ASC": ("Year", False),
            "Year DESC": ("Year", True),
        }

        # Get the corresponding column and reverse flag
        col, reverse = col_map.get(sort_option, ("Title", False))

        # Call the sort_column method to sort the Treeview
        self.sort_column(col, reverse)

    # Adds the selected game to a user-chosen collection.
    def add_to_collection(self):
        game_id, game_title = self.get_selected_game()
        if not game_id:
            return

        try:
            self.controller.curs.execute(
                'SELECT platformid FROM userplatform WHERE userid = %s',
                (self.controller.current_user_id,)
            )
            user_platforms = {row[0] for row in self.controller.curs.fetchall()}

            self.controller.curs.execute(
                'SELECT platformid FROM gameplatform WHERE gameid = %s',
                (game_id,)
            )
            game_platforms = {row[0] for row in self.controller.curs.fetchall()}

            if user_platforms.isdisjoint(game_platforms):
                if not messagebox.askyesno("Platform Warning",
                                           f"Warning: You do not own any of the platforms for '{game_title}'.\n\n"
                                           "Do you still want to add it to a collection?"):
                    return

        except Exception as e:
            messagebox.showerror("Database Error", f"Could not verify platforms: {e}")
            self.controller.conn.rollback()
            return

        try:
            self.controller.curs.execute(
                'SELECT collectionid, name FROM collection WHERE userid = %s ORDER BY name',
                (self.controller.current_user_id,)
            )
            collections = self.controller.curs.fetchall()
            if not collections:
                messagebox.showerror("Error", "You have no collections. Please create one first.")
                return

            collection_names = [name for cid, name in collections]
            choice = self.show_choice_dialog("Add to Collection",
                                             f"Add '{game_title}' to which collection?",
                                             collection_names)

            if choice:
                chosen_collection_id = [cid for cid, name in collections if name == choice][0]

                self.controller.curs.execute(
                    'INSERT INTO collectiongame (collectionid, gameid) VALUES (%s, %s)',
                    (chosen_collection_id, game_id)
                )
                self.controller.conn.commit()
                messagebox.showinfo("Success", f"Added '{game_title}' to '{choice}'.")
                self.controller.frames["MainAppFrame"].collections_frame.load_collections()

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", f"'{game_title}' is already in that collection.")
            else:
                messagebox.showerror("Database Error", f"Failed to add game: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

    # A custom simple dialog to pick from a list.
    def show_choice_dialog(self, title, text, options):
        dialog = tk.Toplevel(self.controller)
        dialog.title(title)
        dialog.transient(self.controller)
        dialog.grab_set()

        ttk.Label(dialog, text=text, font=("Arial", 12)).pack(padx=20, pady=(20, 10))

        choice_var = tk.StringVar(dialog)

        if options:
            choice_var.set(options[0])
            dropdown = ttk.OptionMenu(dialog, choice_var, options[0], *options)
            dropdown.pack(padx=20, pady=10, fill="x")

        result = [None]

        def on_ok():
            result[0] = choice_var.get()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        ttk.Button(button_frame, text="OK", command=on_ok).pack(side="left", padx=10)
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side="right", padx=10)
        button_frame.pack(padx=20, pady=(10, 20))

        self.controller.wait_window(dialog)
        return result[0]

    # Rates the selected game.
    def rate_game(self):
        game_id, game_title = self.get_selected_game()
        if not game_id:
            return

        rating = simpledialog.askinteger("Rate Game", f"Enter your rating (1-5) for '{game_title}':", minvalue=1,
                                         maxvalue=5)
        if not rating:
            return

        try:
            sql = """
                INSERT INTO purchases (userid, gameid, starrating)
                VALUES (%s, %s, %s)
                ON CONFLICT (userid, gameid) 
                DO UPDATE SET starrating = EXCLUDED.starrating;
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id, game_id, rating))
            self.controller.conn.commit()
            messagebox.showinfo("Success", f"Set rating for '{game_title}' to {rating} stars.")

            self.search_games()
            # Refresh profile if it exists
            if hasattr(self.controller.frames["MainAppFrame"], 'profile_frame'):
                self.controller.frames["MainAppFrame"].profile_frame.load_profile()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to rate game: {e}")

    # Logs a play session for the selected game.
    def play_game(self):
        game_id, game_title = self.get_selected_game()
        if not game_id:
            return

        duration = simpledialog.askinteger("Log Play Session", f"How many minutes did you play '{game_title}'?",
                                           minvalue=1)
        if not duration:
            return

        try:
            sql = """
                INSERT INTO plays (userid, gameid, playdatetime, duration)
                VALUES (%s, %s, %s, %s)
            """
            self.controller.curs.execute(sql,
                                         (self.controller.current_user_id, game_id, datetime.datetime.now(), duration))
            self.controller.conn.commit()

            messagebox.showinfo("Success", f"Logged {duration} minutes for '{game_title}'.")

            self.search_games()
            self.controller.frames["MainAppFrame"].collections_frame.load_collections()
            # Refresh profile if it exists
            if hasattr(self.controller.frames["MainAppFrame"], 'profile_frame'):
                self.controller.frames["MainAppFrame"].profile_frame.load_profile()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to log play session: {e}")


# The frame for the "Social" tab.
class SocialFrame(ttk.Frame):
    # Initializes the social UI (search, follow, unfollow).
    def __init__(self, parent, controller):
        ttk.Frame.__init__(self, parent, padding="10")
        self.controller = controller

        find_frame = ttk.Frame(self, padding="10")
        find_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        ttk.Label(find_frame, text="Find Users", font=("Arial", 16)).pack(pady=10)

        search_bar = ttk.Frame(find_frame)
        search_bar.pack(fill="x")

        ttk.Label(search_bar, text="Search by Email:").pack(side="left")
        self.email_entry = ttk.Entry(search_bar, width=30)
        self.email_entry.pack(side="left", padx=5, expand=True)
        ttk.Button(search_bar, text="Search", command=self.search_users).pack(side="left")

        cols_search = ("Username", "Email")
        self.search_tree = ttk.Treeview(find_frame, columns=cols_search, show="headings")
        self.search_tree.heading("Username", text="Username")
        self.search_tree.heading("Email", text="Email")
        self.search_tree.column("Username", width=120)
        self.search_tree.column("Email", width=200)

        self.search_tree['displaycolumns'] = ("Username", "Email")
        self.search_tree["columns"] = ("UserID", "Username", "Email")
        self.search_tree.column("UserID", width=0, stretch=tk.NO)

        self.search_tree.pack(fill="both", expand=True, pady=(10, 0))

        ttk.Button(find_frame, text="Follow Selected User", command=self.follow_user).pack(pady=10)

        following_frame = ttk.Frame(self, padding="10")
        following_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        ttk.Label(following_frame, text="Following", font=("Arial", 16)).pack(pady=10)

        cols_following = ("Username", "Email", "Follow Date")
        self.following_tree = ttk.Treeview(following_frame, columns=cols_following, show="headings")
        self.following_tree.heading("Username", text="Username")
        self.following_tree.heading("Email", text="Email")
        self.following_tree.heading("Follow Date", text="Follow Date")
        self.following_tree.column("Username", width=120)
        self.following_tree.column("Email", width=200)
        self.following_tree.column("Follow Date", width=100)

        self.following_tree['displaycolumns'] = ("Username", "Email", "Follow Date")
        self.following_tree["columns"] = ("UserID", "Username", "Email", "Follow Date")
        self.following_tree.column("UserID", width=0, stretch=tk.NO)

        self.following_tree.pack(fill="both", expand=True)

        ttk.Button(following_frame, text="Unfollow Selected User", command=self.unfollow_user).pack(pady=10)

    # Finds users by email.
    def search_users(self):
        for item in self.search_tree.get_children():
            self.search_tree.delete(item)

        email_query = self.email_entry.get()
        if not email_query:
            return

        try:
            sql = """
                SELECT userid, username, email 
                FROM users 
                WHERE email ILIKE %s AND userid != %s
            """
            self.controller.curs.execute(sql, (f"%{email_query}%", self.controller.current_user_id))

            for row in self.controller.curs.fetchall():
                self.search_tree.insert("", "end", values=row)

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to search users: {e}")
            self.controller.conn.rollback()

    # Loads the list of users the current user is following.
    def load_following(self):
        for item in self.following_tree.get_children():
            self.following_tree.delete(item)

        if not self.controller.current_user_id:
            return

        try:
            sql = """
                SELECT u.userid, u.username, u.email, f.followdate
                FROM follows f
                JOIN users u ON f.followedid = u.userid
                WHERE f.followerid = %s
                ORDER BY u.username ASC;
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id,))

            for row in self.controller.curs.fetchall():
                user_id, username, email, follow_date = row
                date_str = follow_date.strftime("%Y-%m-%d") if follow_date else "N/A"
                self.following_tree.insert("", "end", values=(user_id, username, email, date_str))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load following list: {e}")
            self.controller.conn.rollback()

    # Follows the user selected in the search results.
    def follow_user(self):
        selected_item = self.search_tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a user from the search results to follow.")
            return

        user_id, username, _ = self.search_tree.item(selected_item)['values']

        try:
            sql = """
                INSERT INTO follows (followerid, followedid, followdate)
                VALUES (%s, %s, %s)
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id, user_id, datetime.datetime.now()))
            self.controller.conn.commit()

            messagebox.showinfo("Success", f"You are now following {username}.")
            self.load_following()
            # Refresh profile if it exists
            if hasattr(self.controller.frames["MainAppFrame"], 'profile_frame'):
                self.controller.frames["MainAppFrame"].profile_frame.load_profile()

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", f"You are already following {username}.")
            else:
                messagebox.showerror("Database Error", f"Failed to follow user: {e}")

    # Unfollows the user selected in the "Following" list.
    def unfollow_user(self):
        selected_item = self.following_tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a user from your 'Following' list to unfollow.")
            return

        user_id, username, _, _ = self.following_tree.item(selected_item)['values']

        if not messagebox.askyesno("Confirm", f"Are you sure you want to unfollow {username}?"):
            return

        try:
            sql = """
                DELETE FROM follows 
                WHERE followerid = %s AND followedid = %s
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id, user_id))
            self.controller.conn.commit()

            messagebox.showinfo("Success", f"You have unfollowed {username}.")
            self.load_following()
            # Refresh profile if it exists
            if hasattr(self.controller.frames["MainAppFrame"], 'profile_frame'):
                self.controller.frames["MainAppFrame"].profile_frame.load_profile()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to unfollow user: {e}")


# The frame for the "My Profile" tab.
class ProfileFrame(ttk.Frame):
    # Initializes the profile UI.
    def __init__(self, parent, controller):
        ttk.Frame.__init__(self, parent, padding="10")
        self.controller = controller

        # Main container with scrollbar
        main_container = ttk.Frame(self)
        main_container.pack(fill="both", expand=True)

        # Stats section
        stats_frame = ttk.LabelFrame(main_container, text="Profile Statistics", padding="15")
        stats_frame.pack(fill="x", pady=(0, 10))

        self.collections_label = ttk.Label(stats_frame, text="Collections: 0", font=("Arial", 12))
        self.collections_label.grid(row=0, column=0, padx=20, pady=5, sticky="w")

        self.followers_label = ttk.Label(stats_frame, text="Followers: 0", font=("Arial", 12))
        self.followers_label.grid(row=0, column=1, padx=20, pady=5, sticky="w")

        self.following_label = ttk.Label(stats_frame, text="Following: 0", font=("Arial", 12))
        self.following_label.grid(row=0, column=2, padx=20, pady=5, sticky="w")

        # Top 10 Games section
        top_games_frame = ttk.LabelFrame(main_container, text="Top 10 Games", padding="15")
        top_games_frame.pack(fill="both", expand=True, pady=(0, 10))

        # Sort options
        sort_bar = ttk.Frame(top_games_frame)
        sort_bar.pack(fill="x", pady=(0, 10))

        ttk.Label(sort_bar, text="Sort by:").pack(side="left", padx=5)
        self.sort_var = tk.StringVar(value="rating")
        ttk.Radiobutton(sort_bar, text="Rating", variable=self.sort_var, value="rating",
                        command=self.load_top_games).pack(side="left", padx=5)
        ttk.Radiobutton(sort_bar, text="Playtime", variable=self.sort_var, value="playtime",
                        command=self.load_top_games).pack(side="left", padx=5)
        ttk.Radiobutton(sort_bar, text="Combined (Rating × Playtime)", variable=self.sort_var, value="combined",
                        command=self.load_top_games).pack(side="left", padx=5)

        # Top games tree
        cols = ("Rank", "Title", "Rating", "Playtime", "Score")
        self.top_games_tree = ttk.Treeview(top_games_frame, columns=cols, show="headings", height=10)
        self.top_games_tree.heading("Rank", text="#")
        self.top_games_tree.heading("Title", text="Game Title")
        self.top_games_tree.heading("Rating", text="My Rating")
        self.top_games_tree.heading("Playtime", text="Playtime")
        self.top_games_tree.heading("Score", text="Score")

        self.top_games_tree.column("Rank", width=40, anchor="center")
        self.top_games_tree.column("Title", width=300)
        self.top_games_tree.column("Rating", width=80, anchor="center")
        self.top_games_tree.column("Playtime", width=100, anchor="center")
        self.top_games_tree.column("Score", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(top_games_frame, orient="vertical", command=self.top_games_tree.yview)
        self.top_games_tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.top_games_tree.pack(side="left", fill="both", expand=True)

    # Loads profile statistics.
    def load_profile(self):
        if not self.controller.current_user_id:
            return

        try:
            # Count collections
            self.controller.curs.execute(
                'SELECT COUNT(*) FROM collection WHERE userid = %s',
                (self.controller.current_user_id,)
            )
            collections_count = self.controller.curs.fetchone()[0]
            self.collections_label.config(text=f"Collections: {collections_count}")

            # Count followers
            self.controller.curs.execute(
                'SELECT COUNT(*) FROM follows WHERE followedid = %s',
                (self.controller.current_user_id,)
            )
            followers_count = self.controller.curs.fetchone()[0]
            self.followers_label.config(text=f"Followers: {followers_count}")

            # Count following
            self.controller.curs.execute(
                'SELECT COUNT(*) FROM follows WHERE followerid = %s',
                (self.controller.current_user_id,)
            )
            following_count = self.controller.curs.fetchone()[0]
            self.following_label.config(text=f"Following: {following_count}")

            self.load_top_games()

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load profile: {e}")
            self.controller.conn.rollback()

    # Loads top 10 games based on selected criteria.
    def load_top_games(self):
        for item in self.top_games_tree.get_children():
            self.top_games_tree.delete(item)

        if not self.controller.current_user_id:
            return

        sort_method = self.sort_var.get()

        try:
            if sort_method == "rating":
                sql = """
                    SELECT g.title, pu.starrating, COALESCE(SUM(pl.duration), 0) as totalplaytime
                    FROM purchases pu
                    JOIN videogame g ON pu.gameid = g.gameid
                    LEFT JOIN plays pl ON pu.gameid = pl.gameid AND pl.userid = pu.userid
                    WHERE pu.userid = %s AND pu.starrating IS NOT NULL
                    GROUP BY g.title, pu.starrating
                    ORDER BY pu.starrating DESC, totalplaytime DESC
                    LIMIT 10
                """
            elif sort_method == "playtime":
                sql = """
                    SELECT g.title, pu.starrating, COALESCE(SUM(pl.duration), 0) as totalplaytime
                    FROM plays pl
                    JOIN videogame g ON pl.gameid = g.gameid
                    LEFT JOIN purchases pu ON pl.gameid = pu.gameid AND pl.userid = pu.userid
                    WHERE pl.userid = %s
                    GROUP BY g.title, pu.starrating
                    ORDER BY totalplaytime DESC
                    LIMIT 10
                """
            else:  # combined
                sql = """
                    SELECT g.title, pu.starrating, COALESCE(SUM(pl.duration), 0) as totalplaytime,
                           (COALESCE(pu.starrating, 0) * COALESCE(SUM(pl.duration), 0)) as score
                    FROM videogame g
                    LEFT JOIN purchases pu ON g.gameid = pu.gameid AND pu.userid = %s
                    LEFT JOIN plays pl ON g.gameid = pl.gameid AND pl.userid = %s
                    WHERE (pu.userid = %s OR pl.userid = %s)
                    GROUP BY g.title, pu.starrating
                    HAVING (pu.starrating IS NOT NULL OR SUM(pl.duration) > 0)
                    ORDER BY score DESC
                    LIMIT 10
                """
                params = (self.controller.current_user_id,) * 4

            if sort_method != "combined":
                params = (self.controller.current_user_id,)

            self.controller.curs.execute(sql, params)

            for idx, row in enumerate(self.controller.curs.fetchall(), 1):
                if sort_method == "combined":
                    title, rating, playtime, score = row
                    score_str = f"{score:.0f}"
                else:
                    title, rating, playtime = row
                    score_str = "N/A"

                rating_str = f"{rating} ★" if rating else "N/A"
                playtime_str = format_duration(playtime)

                self.top_games_tree.insert("", "end", values=(
                    idx, title, rating_str, playtime_str, score_str
                ))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load top games: {e}")
            self.controller.conn.rollback()


# The frame for the "Popular & Recommended" tab.
class PopularFrame(ttk.Frame):
    # Initializes the popular games and recommendations UI.
    def __init__(self, parent, controller):
        ttk.Frame.__init__(self, parent, padding="10")
        self.controller = controller

        # Create notebook for sub-tabs
        self.sub_notebook = ttk.Notebook(self)
        self.sub_notebook.pack(fill="both", expand=True)

        # Popular in Last 90 Days
        self.popular_90_frame = ttk.Frame(self.sub_notebook, padding="10")
        self.sub_notebook.add(self.popular_90_frame, text="Top 20 - Last 90 Days")

        ttk.Label(self.popular_90_frame, text="Most Popular Games (Last 90 Days)",
                  font=("Arial", 14)).pack(pady=10)

        cols = ("Rank", "Title", "Plays", "Total Playtime", "Unique Players")
        self.popular_90_tree = ttk.Treeview(self.popular_90_frame, columns=cols, show="headings")
        for col in cols:
            self.popular_90_tree.heading(col, text=col)
        self.popular_90_tree.column("Rank", width=50, anchor="center")
        self.popular_90_tree.column("Title", width=250)
        self.popular_90_tree.column("Plays", width=80, anchor="center")
        self.popular_90_tree.column("Total Playtime", width=120, anchor="center")
        self.popular_90_tree.column("Unique Players", width=120, anchor="center")

        scroll_90 = ttk.Scrollbar(self.popular_90_frame, orient="vertical", command=self.popular_90_tree.yview)
        self.popular_90_tree.configure(yscrollcommand=scroll_90.set)
        scroll_90.pack(side="right", fill="y")
        self.popular_90_tree.pack(fill="both", expand=True)

        # Popular Among Followed Users
        self.followed_frame = ttk.Frame(self.sub_notebook, padding="10")
        self.sub_notebook.add(self.followed_frame, text="Top 20 - Followed Users")

        ttk.Label(self.followed_frame, text="Most Popular Among Users You Follow",
                  font=("Arial", 14)).pack(pady=10)

        cols_followed = ("Rank", "Title", "Plays", "Total Playtime", "Players Following")
        self.followed_tree = ttk.Treeview(self.followed_frame, columns=cols_followed, show="headings")
        for col in cols_followed:
            self.followed_tree.heading(col, text=col)
        self.followed_tree.column("Rank", width=50, anchor="center")
        self.followed_tree.column("Title", width=250)
        self.followed_tree.column("Plays", width=80, anchor="center")
        self.followed_tree.column("Total Playtime", width=120, anchor="center")
        self.followed_tree.column("Players Following", width=120, anchor="center")

        scroll_followed = ttk.Scrollbar(self.followed_frame, orient="vertical", command=self.followed_tree.yview)
        self.followed_tree.configure(yscrollcommand=scroll_followed.set)
        scroll_followed.pack(side="right", fill="y")
        self.followed_tree.pack(fill="both", expand=True)

        # New Releases This Month
        self.new_releases_frame = ttk.Frame(self.sub_notebook, padding="10")
        self.sub_notebook.add(self.new_releases_frame, text="Top 5 New Releases")

        ttk.Label(self.new_releases_frame, text="Top 5 New Releases This Month",
                  font=("Arial", 14)).pack(pady=10)

        cols_new = ("Rank", "Title", "Release Date", "Platform", "Publisher")
        self.new_releases_tree = ttk.Treeview(self.new_releases_frame, columns=cols_new, show="headings")
        for col in cols_new:
            self.new_releases_tree.heading(col, text=col)
        self.new_releases_tree.column("Rank", width=50, anchor="center")
        self.new_releases_tree.column("Title", width=250)
        self.new_releases_tree.column("Release Date", width=100, anchor="center")
        self.new_releases_tree.column("Platform", width=150)
        self.new_releases_tree.column("Publisher", width=150)

        scroll_new = ttk.Scrollbar(self.new_releases_frame, orient="vertical", command=self.new_releases_tree.yview)
        self.new_releases_tree.configure(yscrollcommand=scroll_new.set)
        scroll_new.pack(side="right", fill="y")
        self.new_releases_tree.pack(fill="both", expand=True)

        # Recommendations
        self.recommendations_frame = ttk.Frame(self.sub_notebook, padding="10")
        self.sub_notebook.add(self.recommendations_frame, text="Recommended For You")

        ttk.Label(self.recommendations_frame, text="Recommended Games Based on Your History",
                  font=("Arial", 14)).pack(pady=10)

        cols_rec = ("Title", "Reason", "Match Score", "Avg Rating")
        self.recommendations_tree = ttk.Treeview(self.recommendations_frame, columns=cols_rec, show="headings")
        for col in cols_rec:
            self.recommendations_tree.heading(col, text=col)
        self.recommendations_tree.column("Title", width=200)
        self.recommendations_tree.column("Reason", width=250)
        self.recommendations_tree.column("Match Score", width=100, anchor="center")
        self.recommendations_tree.column("Avg Rating", width=100, anchor="center")

        scroll_rec = ttk.Scrollbar(self.recommendations_frame, orient="vertical",
                                   command=self.recommendations_tree.yview)
        self.recommendations_tree.configure(yscrollcommand=scroll_rec.set)
        scroll_rec.pack(side="right", fill="y")
        self.recommendations_tree.pack(fill="both", expand=True)

        # Refresh button
        refresh_btn = ttk.Button(self.recommendations_frame, text="Refresh Recommendations",
                                 command=lambda: self.refresh_recommendations())
        refresh_btn.pack(pady=10)

        # Bind sub-notebook tab change to load data on demand
        self.sub_notebook.bind("<<NotebookTabChanged>>", self.on_subtab_changed)

    # Refresh recommendations (clear and reload)
    def refresh_recommendations(self):
        for item in self.recommendations_tree.get_children():
            self.recommendations_tree.delete(item)
        self.load_recommendations()

    # Handles sub-tab changes to load data on demand.
    def on_subtab_changed(self, event):
        selected_tab = event.widget.select()
        tab_text = event.widget.tab(selected_tab, "text")

        if tab_text == "Recommended For You" and not self.recommendations_tree.get_children():
            # Only load if empty (first time)
            self.load_recommendations()

    # Loads all data for this tab.
    def load_data(self):
        self.load_popular_90_days()
        self.load_popular_followed()
        self.load_new_releases()
        # Don't load recommendations immediately - wait for user to click the tab

    # Loads top 20 most popular games in last 90 days.
    def load_popular_90_days(self):
        for item in self.popular_90_tree.get_children():
            self.popular_90_tree.delete(item)

        try:
            sql = """
                SELECT g.title, COUNT(*) as playcount, SUM(pl.duration) as totalplaytime, 
                       COUNT(DISTINCT pl.userid) as uniqueplayers
                FROM plays pl
                JOIN videogame g ON pl.gameid = g.gameid
                WHERE pl.playdatetime >= CURRENT_DATE - INTERVAL '90 days'
                GROUP BY g.title
                ORDER BY playcount DESC, totalplaytime DESC
                LIMIT 20
            """
            self.controller.curs.execute(sql)

            for idx, row in enumerate(self.controller.curs.fetchall(), 1):
                title, plays, playtime, players = row
                playtime_str = format_duration(playtime)
                self.popular_90_tree.insert("", "end", values=(
                    idx, title, plays, playtime_str, players
                ))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load popular games: {e}")
            self.controller.conn.rollback()

    # Loads top 20 games popular among followed users.
    def load_popular_followed(self):
        for item in self.followed_tree.get_children():
            self.followed_tree.delete(item)

        if not self.controller.current_user_id:
            return

        try:
            sql = """
                SELECT g.title, COUNT(*) as playcount, SUM(pl.duration) as totalplaytime,
                       COUNT(DISTINCT pl.userid) as uniqueplayers
                FROM plays pl
                JOIN videogame g ON pl.gameid = g.gameid
                WHERE pl.userid IN (
                    SELECT followedid FROM follows WHERE followerid = %s
                )
                GROUP BY g.title
                ORDER BY playcount DESC, totalplaytime DESC
                LIMIT 20
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id,))

            for idx, row in enumerate(self.controller.curs.fetchall(), 1):
                title, plays, playtime, players = row
                playtime_str = format_duration(playtime)
                self.followed_tree.insert("", "end", values=(
                    idx, title, plays, playtime_str, players
                ))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load followed games: {e}")
            self.controller.conn.rollback()

    # Loads top 5 new releases this month.
    def load_new_releases(self):
        for item in self.new_releases_tree.get_children():
            self.new_releases_tree.delete(item)

        try:
            sql = """
                SELECT g.title, gp.releasedate, 
                       STRING_AGG(DISTINCT p.name, ', ') as platforms,
                       STRING_AGG(DISTINCT c.name, ', ') as publishers
                FROM videogame g
                JOIN gameplatform gp ON g.gameid = gp.gameid
                LEFT JOIN platform p ON gp.platformid = p.platformid
                LEFT JOIN gamepublisher gpub ON g.gameid = gpub.gameid
                LEFT JOIN company c ON gpub.companyid = c.companyid
                WHERE EXTRACT(YEAR FROM gp.releasedate) = EXTRACT(YEAR FROM CURRENT_DATE)
                  AND EXTRACT(MONTH FROM gp.releasedate) = EXTRACT(MONTH FROM CURRENT_DATE)
                GROUP BY g.title, gp.releasedate
                ORDER BY gp.releasedate DESC
                LIMIT 5
            """
            self.controller.curs.execute(sql)

            for idx, row in enumerate(self.controller.curs.fetchall(), 1):
                title, release_date, platforms, publishers = row
                date_str = release_date.strftime("%Y-%m-%d") if release_date else "N/A"
                self.new_releases_tree.insert("", "end", values=(
                    idx, title, date_str, platforms or "N/A", publishers or "N/A"
                ))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load new releases: {e}")
            self.controller.conn.rollback()

    # Loads personalized game recommendations.
    def load_recommendations(self):
        for item in self.recommendations_tree.get_children():
            self.recommendations_tree.delete(item)

        if not self.controller.current_user_id:
            return

        try:
            # Simplified and optimized recommendation query
            sql_preferences = """
                WITH user_games AS (
                    -- Games user already has
                    SELECT DISTINCT cg.gameid
                    FROM collectiongame cg
                    JOIN collection c ON cg.collectionid = c.collectionid
                    WHERE c.userid = %s
                ),
                user_genres AS (
                    -- Top 3 favorite genres
                    SELECT gg.genreid
                    FROM user_games ug
                    JOIN gamegenre gg ON ug.gameid = gg.gameid
                    GROUP BY gg.genreid
                    ORDER BY COUNT(*) DESC
                    LIMIT 3
                ),
                user_developers AS (
                    -- Top 3 favorite developers
                    SELECT gd.companyid
                    FROM user_games ug
                    JOIN gamedeveloper gd ON ug.gameid = gd.gameid
                    GROUP BY gd.companyid
                    ORDER BY COUNT(*) DESC
                    LIMIT 3
                )
                SELECT DISTINCT ON (g.gameid) g.gameid, g.title,
                       CASE 
                           WHEN gg.genreid IS NOT NULL THEN 'Favorite Genre'
                           WHEN gd.companyid IS NOT NULL THEN 'Favorite Developer'
                           ELSE 'Popular Choice'
                       END as reason,
                       (CASE WHEN gg.genreid IS NOT NULL THEN 3 ELSE 0 END +
                        CASE WHEN gd.companyid IS NOT NULL THEN 3 ELSE 0 END) as score,
                       COALESCE(
                           (SELECT AVG(starrating) FROM purchases WHERE gameid = g.gameid),
                           0
                       ) as avg_rating
                FROM videogame g
                LEFT JOIN gamegenre gg ON g.gameid = gg.gameid AND gg.genreid IN (SELECT genreid FROM user_genres)
                LEFT JOIN gamedeveloper gd ON g.gameid = gd.gameid AND gd.companyid IN (SELECT companyid FROM user_developers)
                WHERE g.gameid NOT IN (SELECT gameid FROM user_games)
                  AND (gg.genreid IS NOT NULL OR gd.companyid IS NOT NULL)
                ORDER BY g.gameid, score DESC, avg_rating DESC
                LIMIT 20
            """

            self.controller.curs.execute(sql_preferences, (self.controller.current_user_id,))
            results = self.controller.curs.fetchall()

            if not results:
                # Fallback: show highly rated games
                sql_fallback = """
                    SELECT DISTINCT g.gameid, g.title, 'Highly Rated' as reason, 
                           3 as score, COALESCE(AVG(pu.starrating), 0) as avg_rating
                    FROM videogame g
                    LEFT JOIN purchases pu ON g.gameid = pu.gameid
                    WHERE g.gameid NOT IN (
                        SELECT DISTINCT cg.gameid
                        FROM collectiongame cg
                        JOIN collection c ON cg.collectionid = c.collectionid
                        WHERE c.userid = %s
                    )
                    GROUP BY g.gameid, g.title
                    HAVING AVG(pu.starrating) >= 4
                    ORDER BY avg_rating DESC
                    LIMIT 20
                """
                self.controller.curs.execute(sql_fallback, (self.controller.current_user_id,))
                results = self.controller.curs.fetchall()

            for row in results:
                game_id, title, reason, score, avg_rating = row
                rating_str = f"{avg_rating:.1f} ★" if avg_rating > 0 else "N/A"
                self.recommendations_tree.insert("", "end", values=(
                    title, reason, f"{score}", rating_str
                ))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load recommendations: {e}")
            self.controller.conn.rollback()


# Main execution block to run the application.
if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()