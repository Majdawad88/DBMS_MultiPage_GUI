# git clone https://github.com/Majdawad88/DBMS_MultiPage_GUI.git
#good
# === IMPORTS ===
import tkinter as tk                          # Main GUI library for building the windows and buttons
from tkinter import ttk, messagebox           # ttk = themed widgets; messagebox = pop-up dialogs
import serial                                 # pyserial library for talking to the Arduino over USB
import time                                   # Used for sleep() to wait for Arduino to reset
import matplotlib                             # Plotting library (imported first so we can set backend)
matplotlib.use('TkAgg')                       # Force the Tk-friendly backend so matplotlib + tkinter share one event loop
import matplotlib.pyplot as plt               # pyplot = convenient plotting interface
import csv                                    # For reading and writing CSV files
import os                                     # Operating-system utilities (not heavily used here, kept for flexibility)
import glob                                   # For finding files by pattern (e.g., all "LDR-rawdata_*.csv")

# === CONSTANTS ===
SERIAL_PORT = '/dev/ttyACM0'                  # The USB port where Arduino shows up on Raspberry Pi / Linux
BAUD_RATE = 9600                              # Must match the Arduino sketch's Serial.begin(9600)
MAX_READINGS = 200                            # How many light-level samples to collect per recording session
PLOT_UPDATE_INTERVAL = 5                      # Redraw the plot every N new samples (smaller = smoother but slower)


# === MAIN APPLICATION CLASS ===
class LDRApp(tk.Tk):
    # LDRApp IS the main window (inherits from tk.Tk = the root window)
    def __init__(self):
        super().__init__()                    # Initialize the underlying Tk window
        self.title("Arduino LDR Dashboard")   # Window title shown in the title bar
        self.geometry("400x400")              # Fixed window size: 400 px wide, 400 px tall

        # A "container" frame that will hold all the pages stacked on top of each other
        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)  # Fill the whole window
        container.grid_rowconfigure(0, weight=1)              # Make the single row stretch to fill height
        container.grid_columnconfigure(0, weight=1)           # Make the single column stretch to fill width

        # Dictionary that maps each Page class -> its created frame instance
        self.frames = {}
        # Create one instance of each page and keep it around (they all exist simultaneously, just hidden)
        for F in (HomePage, RecordPage, DisplayPage):
            frame = F(container, self)                        # Pass container as parent, self as controller
            self.frames[F] = frame                            # Store it by its class for later lookup
            frame.grid(row=0, column=0, sticky="nsew")        # Put every page in the same grid cell

        self.show_frame(HomePage)                             # Start on the Home page

    def show_frame(self, page_class):
        # Bring the requested page to the front (hides the others)
        frame = self.frames[page_class]
        # If we're switching to the Display page, refresh the list of CSV files first
        if page_class == DisplayPage:
            frame.refresh_file_list()
        frame.tkraise()                                       # Tk magic: raise this frame above the others


# === HOME PAGE ===
class HomePage(tk.Frame):
    # Simple page with two navigation buttons
    def __init__(self, parent, controller):
        super().__init__(parent)                              # Initialize as a Frame inside the container

        # Big title label at the top
        label = tk.Label(self, text="HOME PAGE", font=("Arial", 16, "bold"))
        label.pack(pady=40)                                   # pady = vertical padding above/below the widget

        # Button that navigates to the Record page
        record_btn = tk.Button(self, text="Record Data", width=20, height=2,
                               command=lambda: controller.show_frame(RecordPage))  # lambda delays the call
        record_btn.pack(pady=10)

        # Button that navigates to the Display page
        display_btn = tk.Button(self, text="Display Data", width=20, height=2,
                                command=lambda: controller.show_frame(DisplayPage))
        display_btn.pack(pady=10)


# === RECORD PAGE ===
class RecordPage(tk.Frame):
    # Page where the user records live data from the Arduino
    def __init__(self, parent, controller):
        super().__init__(parent)                              # Initialize as a Frame
        self.controller = controller                          # Keep a reference so we can switch pages
        self.data = []                                        # List where incoming sensor readings are stored
        self.ser = None                                       # Serial port object (created later)
        self.fig = None                                       # Matplotlib figure (created later)

        # Title label
        label = tk.Label(self, text="RECORD PAGE", font=("Arial", 16, "bold"))
        label.pack(pady=20)

        # Green "Start Recording" button — calls start_recording() when clicked
        self.record_btn = tk.Button(self, text="Start Recording", width=20, height=2,
                                    bg="lightgreen", command=self.start_recording)
        self.record_btn.pack(pady=10)

        # Progress counter (e.g., "Readings: 37 / 200")
        self.progress_label = tk.Label(self, text="Readings: 0 / 200")
        self.progress_label.pack(pady=5)

        # "Go Back" button to return to the Home page
        back_btn = tk.Button(self, text="Go Back", width=20,
                             command=lambda: controller.show_frame(HomePage))
        back_btn.pack(pady=20)

    def start_recording(self):
        # Try to open the serial port to talk to the Arduino
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)  # timeout=0.1 = don't block too long
            time.sleep(2)                                     # Arduino resets on connection; wait for it to boot
            self.ser.reset_input_buffer()                     # Throw away any garbage bytes from boot-up
        except serial.SerialException:
            # If the port can't be opened, show an error and stop here
            messagebox.showerror(
                "Connection Error",
                f"Could not connect to {SERIAL_PORT}. "
                f"Is the Arduino plugged in and the Serial Monitor closed?"
            )
            return

        # Disable the button and change its text so the user knows recording is in progress
        self.record_btn.config(state=tk.DISABLED, text="Recording...")
        self.data = []                                        # Clear any previous readings

        # === Set up the live matplotlib plot ===
        plt.ion()                                             # "Interactive mode" — plot updates without blocking
        self.fig, self.ax = plt.subplots()                    # Create a new figure and axes
        self.fig.canvas.manager.set_window_title('Live LDR Data')   # Set the plot window's title bar
        self.line, = self.ax.plot([], [], marker='o', markersize=3) # Empty line we'll update as data comes in
        self.ax.set_xlim(0, MAX_READINGS)                     # X-axis: 0 to 200 readings
        self.ax.set_ylim(0, 1024)                             # Y-axis: 0-1023 (Arduino analogRead range)
        self.ax.set_title("Live LDR Sensor Data (10 seconds)")
        self.ax.set_xlabel("Reading Number")
        self.ax.set_ylabel("Light Level")

        # Kick off the first iteration of the read loop
        self.read_serial_step()

    def read_serial_step(self):
        # This function runs repeatedly (scheduled via self.after) until we have 200 readings
        if len(self.data) < MAX_READINGS:
            got_new_data = False                              # Did we grab a fresh reading this tick?

            # Only try to read if there's actually data waiting (non-blocking)
            if self.ser.in_waiting:
                try:
                    # Read one full line from Arduino. errors='replace' prevents crashes on stray bytes.
                    line_data = self.ser.readline().decode('utf-8', errors='replace').strip()
                    if line_data.isdigit():                   # Only accept pure numeric lines
                        self.data.append(int(line_data))      # Store the reading
                        got_new_data = True
                except Exception as e:
                    print(f"Serial read error: {e}")          # Log it but keep going

            if got_new_data:
                # Update the "Readings: X / 200" label
                self.progress_label.config(
                    text=f"Readings: {len(self.data)} / {MAX_READINGS}"
                )

                # Redraw the plot every N samples (and one final time at the very end)
                if len(self.data) % PLOT_UPDATE_INTERVAL == 0 or len(self.data) == MAX_READINGS:
                    self.line.set_xdata(range(len(self.data)))   # Update X values (0, 1, 2, ...)
                    self.line.set_ydata(self.data)               # Update Y values (the readings)
                    try:
                        self.fig.canvas.draw_idle()              # Request a redraw (coalesces multiple requests)
                        self.fig.canvas.flush_events()           # Process the redraw immediately
                    except Exception:
                        pass                                     # User may have closed the plot — ignore it

            # Schedule this function to run again in 25 ms (non-blocking, keeps GUI responsive)
            self.after(25, self.read_serial_step)
        else:
            # We've hit MAX_READINGS — recording is complete, begin cleanup
            self.finish_recording()

    def finish_recording(self):
        """Safely tear down serial + plot, then show success dialog."""
        # 1. Close the serial port so another program can use it
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception as e:
            print(f"Error closing serial: {e}")

        # 2. Close the matplotlib figure to free up resources
        try:
            if self.fig is not None:
                plt.close(self.fig)
                self.fig = None                               # Clear reference so we don't try to reuse it
        except Exception as e:
            print(f"Error closing plot: {e}")

        plt.ioff()                                            # Turn off interactive mode

        # 3. Restore the button BEFORE showing the dialog (in case dialog misbehaves, button still works)
        self.record_btn.config(state=tk.NORMAL, text="Start Recording")
        self.progress_label.config(text="Readings: 0 / 200")

        # 4. Force Tk to process all pending screen updates so the GUI refreshes immediately
        self.update_idletasks()
        self.update()

        # 5. Save CSV and show popup on the next event-loop tick — prevents dialog from blocking cleanup
        self.after(100, self.save_and_notify)

    def save_and_notify(self):
        """Save the CSV and show the success popup."""
        try:
            # Find all existing LDR-rawdata_*.csv files to determine next number
            existing_files = glob.glob("LDR-rawdata_*.csv")
            max_num = 0
            for f in existing_files:
                try:
                    # Extract the number between "_" and ".csv" (e.g., "LDR-rawdata_6.csv" -> 6)
                    num = int(f.split('_')[1].split('.')[0])
                    if num > max_num:
                        max_num = num
                except (ValueError, IndexError):
                    continue                                  # Skip any file that doesn't match the pattern

            # New file will be one higher than the highest existing number
            new_filename = f"LDR-rawdata_{max_num + 1}.csv"

            # Write all readings to the CSV, one per row
            with open(new_filename, 'w', newline='') as file:
                writer = csv.writer(file)
                for val in self.data:
                    writer.writerow([val])                    # Each row is a single-column value

            # Confirmation popup. parent=self keeps the dialog properly tied to our window.
            messagebox.showinfo("Success", f"Data saved to {new_filename}", parent=self)
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save CSV: {e}", parent=self)


# === DISPLAY PAGE ===
class DisplayPage(tk.Frame):
    # Page where the user picks saved CSV files and plots them together
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.file_vars = {}                                   # Maps filename -> its Checkbutton BooleanVar

        # Title label
        label = tk.Label(self, text="DISPLAY PAGE", font=("Arial", 16, "bold"))
        label.pack(pady=20)

        # A frame that will hold a list of checkboxes (one per CSV file found)
        self.checkbox_frame = tk.Frame(self)
        self.checkbox_frame.pack(pady=10, fill="both", expand=True)

        # Button that plots all selected CSVs
        display_btn = tk.Button(self, text="Display Selected", width=20, height=2,
                                bg="lightblue", command=self.display_selected_data)
        display_btn.pack(pady=10)

        # Back-to-home button
        back_btn = tk.Button(self, text="Go Back", width=20,
                             command=lambda: controller.show_frame(HomePage))
        back_btn.pack(pady=10)

    def refresh_file_list(self):
        # Called every time the user navigates to the Display page
        # Clear any existing checkboxes first
        for widget in self.checkbox_frame.winfo_children():
            widget.destroy()
        self.file_vars.clear()                                # Reset the mapping

        # Find all CSVs matching our naming pattern, alphabetically sorted
        files = sorted(glob.glob("LDR-rawdata_*.csv"))

        # If there are no files, show a helpful message
        if not files:
            tk.Label(self.checkbox_frame, text="No recorded data found yet.").pack()
            return

        # Otherwise, make one checkbox per file
        for f in files:
            var = tk.BooleanVar()                             # A Tk boolean variable tied to the checkbox state
            chk = tk.Checkbutton(self.checkbox_frame, text=f, variable=var)
            chk.pack(anchor='w', padx=50)                     # anchor='w' = align to left side
            self.file_vars[f] = var                           # Remember which var belongs to which file

    def display_selected_data(self):
        # Get the list of files whose checkbox is ticked
        selected_files = [f for f, var in self.file_vars.items() if var.get()]

        # Warn the user if they didn't select anything
        if not selected_files:
            messagebox.showwarning("No Selection", "Please check at least one CSV file to display.",
                                   parent=self)
            return

        columns = []                                          # Will hold each file's data as a list
        headers = []                                          # Will hold the corresponding filenames

        # Set up a single plot window for all the overlaid curves
        plt.figure("Combined Plot Data")
        plt.title("Combined LDR Sensor Readings")
        plt.xlabel("Reading Number")
        plt.ylabel("Light Level")

        # Loop through each selected file, read its contents, and plot it
        for f in selected_files:
            try:
                with open(f, 'r') as file:
                    reader = csv.reader(file)
                    # Convert every non-empty row's first column into an integer
                    col_data = [int(row[0]) for row in reader if row]
                    columns.append(col_data)
                    headers.append(f)
                    plt.plot(col_data, label=f)               # Add this file's curve to the plot
            except Exception as e:
                print(f"Error reading {f}: {e}")

        plt.legend()                                          # Show a legend with filenames
        plt.grid(True)                                        # Add gridlines for easier reading

        # Also write all selected data into one combined CSV file
        try:
            with open("COMBINED_LDR_RAWDATA.csv", "w", newline="") as out_file:
                writer = csv.writer(out_file)
                writer.writerow(headers)                      # First row = filenames as column headers
                # zip(*columns) transposes our list of columns into rows
                for row in zip(*columns):
                    writer.writerow(row)
            messagebox.showinfo("Success",
                                "Selected data combined and saved to COMBINED_LDR_RAWDATA.csv",
                                parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save combined CSV: {e}", parent=self)

        plt.show(block=False)                                 # Non-blocking so the GUI stays responsive


# === ENTRY POINT ===
if __name__ == "__main__":
    app = LDRApp()                                            # Create the main window
    app.mainloop()                                            # Start Tk's event loop (runs until window closes)
