# git clone 


import tkinter as tk
from tkinter import ttk, messagebox
import serial
import matplotlib.pyplot as plt
import csv
import os
import glob

# Constants
SERIAL_PORT = 'COM16'
BAUD_RATE = 9600
MAX_READINGS = 200

class LDRApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Arduino LDR Dashboard")
        self.geometry("400x400")
        
        # Create a container to hold all the frames (pages)
        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        # Initialize all pages
        for F in (HomePage, RecordPage, DisplayPage):
            frame = F(container, self)
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame(HomePage)

    def show_frame(self, page_class):
        frame = self.frames[page_class]
        # If we navigate to the Display Page, refresh the list of CSVs
        if page_class == DisplayPage:
            frame.refresh_file_list()
        frame.tkraise()

class HomePage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        label = tk.Label(self, text="HOME PAGE", font=("Arial", 16, "bold"))
        label.pack(pady=40)

        record_btn = tk.Button(self, text="Record Data", width=20, height=2, 
                               command=lambda: controller.show_frame(RecordPage))
        record_btn.pack(pady=10)

        display_btn = tk.Button(self, text="Display Data", width=20, height=2, 
                                command=lambda: controller.show_frame(DisplayPage))
        display_btn.pack(pady=10)

class RecordPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.data = []
        self.ser = None

        label = tk.Label(self, text="RECORD PAGE", font=("Arial", 16, "bold"))
        label.pack(pady=20)

        self.record_btn = tk.Button(self, text="Start Recording", width=20, height=2, 
                                    bg="lightgreen", command=self.start_recording)
        self.record_btn.pack(pady=10)

        self.progress_label = tk.Label(self, text="Readings: 0 / 200")
        self.progress_label.pack(pady=5)

        back_btn = tk.Button(self, text="Go Back", width=20, 
                             command=lambda: controller.show_frame(HomePage))
        back_btn.pack(pady=20)

    def start_recording(self):
        try:
            # Open Serial Port
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        except serial.SerialException:
            messagebox.showerror("Connection Error", f"Could not connect to {SERIAL_PORT}. Is the Arduino plugged in and the Serial Monitor closed?")
            return

        self.record_btn.config(state=tk.DISABLED, text="Recording...")
        self.data = []
        
        # Setup Live Plot
        plt.ion() # Turn on interactive mode
        self.fig, self.ax = plt.subplots()
        self.fig.canvas.manager.set_window_title('Live LDR Data')
        self.line, = self.ax.plot([], [], marker='o', markersize=3)
        self.ax.set_xlim(0, MAX_READINGS)
        self.ax.set_ylim(0, 1024) # Analog read max is 1023
        self.ax.set_title("Live LDR Sensor Data")
        self.ax.set_xlabel("Reading Number")
        self.ax.set_ylabel("Light Level")

        # Start the read loop
        self.read_serial_step()

    def read_serial_step(self):
        if len(self.data) < MAX_READINGS:
            # Check if there's data waiting on the serial port
            if self.ser.in_waiting:
                try:
                    line_data = self.ser.readline().decode('utf-8').strip()
                    if line_data.isdigit():
                        self.data.append(int(line_data))
                        
                        # Update Live Plot
                        self.line.set_xdata(range(len(self.data)))
                        self.line.set_ydata(self.data)
                        try:
                            self.fig.canvas.draw()
                            self.fig.canvas.flush_events()
                        except:
                            pass # Handles user closing the plot window early
                        
                        self.progress_label.config(text=f"Readings: {len(self.data)} / {MAX_READINGS}")
                except Exception as e:
                    print(f"Serial read error: {e}")

            # Schedule this function to run again in 10ms (prevents GUI from freezing)
            self.after(10, self.read_serial_step)
        else:
            # 200 readings complete
            self.ser.close()
            plt.close(self.fig)
            plt.ioff()
            self.save_data()
            self.record_btn.config(state=tk.NORMAL, text="Start Recording")
            self.progress_label.config(text="Readings: 0 / 200")

    def save_data(self):
        # Figure out the next file number
        existing_files = glob.glob("LDR-rawdata_*.csv")
        max_num = 0
        for f in existing_files:
            try:
                # Extract the number from 'LDR-rawdata_X.csv'
                num = int(f.split('_')[1].split('.')[0])
                if num > max_num:
                    max_num = num
            except ValueError:
                continue
        
        new_filename = f"LDR-rawdata_{max_num + 1}.csv"
        
        # Write to CSV
        with open(new_filename, 'w', newline='') as file:
            writer = csv.writer(file)
            for val in self.data:
                writer.writerow([val])
                
        messagebox.showinfo("Success", f"Data saved to {new_filename}")

class DisplayPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.file_vars = {} # Dictionary to store checkbutton variables

        label = tk.Label(self, text="DISPLAY PAGE", font=("Arial", 16, "bold"))
        label.pack(pady=20)

        # Frame to hold the dynamic list of checkboxes
        self.checkbox_frame = tk.Frame(self)
        self.checkbox_frame.pack(pady=10, fill="both", expand=True)

        display_btn = tk.Button(self, text="Display Selected", width=20, height=2, 
                                bg="lightblue", command=self.display_selected_data)
        display_btn.pack(pady=10)

        back_btn = tk.Button(self, text="Go Back", width=20, 
                             command=lambda: controller.show_frame(HomePage))
        back_btn.pack(pady=10)

    def refresh_file_list(self):
        # Clear existing checkboxes
        for widget in self.checkbox_frame.winfo_children():
            widget.destroy()
        self.file_vars.clear()

        # Find all CSV files matching our pattern
        files = sorted(glob.glob("LDR-rawdata_*.csv"))
        
        if not files:
            tk.Label(self.checkbox_frame, text="No recorded data found yet.").pack()
            return

        for f in files:
            var = tk.BooleanVar()
            chk = tk.Checkbutton(self.checkbox_frame, text=f, variable=var)
            chk.pack(anchor='w', padx=50)
            self.file_vars[f] = var

    def display_selected_data(self):
        selected_files = [f for f, var in self.file_vars.items() if var.get()]
        
        if not selected_files:
            messagebox.showwarning("No Selection", "Please check at least one CSV file to display.")
            return

        columns = []
        headers = []

        # Setup Static Plot
        plt.figure("Combined Plot Data")
        plt.title("Combined LDR Sensor Readings")
        plt.xlabel("Reading Number")
        plt.ylabel("Light Level")

        for f in selected_files:
            try:
                with open(f, 'r') as file:
                    reader = csv.reader(file)
                    # Extract single column of data from the file
                    col_data = [int(row[0]) for row in reader if row]
                    columns.append(col_data)
                    headers.append(f)
                    # Plot it on the same X-axis
                    plt.plot(col_data, label=f)
            except Exception as e:
                print(f"Error reading {f}: {e}")

        plt.legend()
        plt.grid(True)
        
        # Save combined data to a new CSV
        try:
            with open("COMBINED_LDR_RAWDATA.csv", "w", newline="") as out_file:
                writer = csv.writer(out_file)
                writer.writerow(headers) # Header row with file names
                
                # Zip transposes the columns into rows
                for row in zip(*columns):
                    writer.writerow(row)
            messagebox.showinfo("Success", "Selected data combined and saved to COMBINED_LDR_RAWDATA.csv")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save combined CSV: {e}")

        # Show the plot
        plt.show()

if __name__ == "__main__":
    app = LDRApp()
    app.mainloop()
